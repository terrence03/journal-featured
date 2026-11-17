"""Fetch recent articles from OpenAlex, filling missing abstracts from Crossref and publishers."""

import html
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date

import requests

log = logging.getLogger(__name__)

OPENALEX = "https://api.openalex.org"
CROSSREF = "https://api.crossref.org"
FIELDS = "id,doi,title,publication_date,abstract_inverted_index,authorships,primary_location,type"

# Notices that aren't research content; OpenAlex doesn't always type them as erratum.
NOTICE_TITLE = re.compile(
    r"^(author correction|publisher correction|correction|erratum|corrigendum|addendum|retraction"
    r"|retracted|editorial expression of concern|expression of concern)\b",
    re.I,
)

_session = requests.Session()
_session.headers["User-Agent"] = "journal-featured/0.1"


@dataclass
class Article:
    doi: str
    title: str
    journal: str
    published: str
    abstract: str
    authors: list[str] = field(default_factory=list)
    url: str = ""
    # filled by score.py
    topic: str = ""  # best-scoring topic
    score: float = 0.0
    scores: dict[str, float] = field(default_factory=dict)  # every topic
    matches: list[str] = field(default_factory=list)  # topics passing their threshold, best first
    # filled by curate.py
    note: str = ""  # Claude's one-line take
    selected: bool = False

    @property
    def text(self) -> str:
        return f"{self.title}. {self.abstract}".strip()


class FetchError(requests.RequestException):
    """A failed request whose message is safe to log, store and show (API keys removed)."""


def redact(text: str) -> str:
    """Hide API keys that `requests` puts in its error messages as part of the URL."""
    return re.sub(r"(api_?key=)[^&\s'\")]+", r"\1***", text, flags=re.I)


def _request(url: str, params: dict, retries: int = 4) -> requests.Response:
    for attempt in range(retries):
        try:
            r = _session.get(url, params=params, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
            r.raise_for_status()
            return r
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            if attempt == retries - 1 or (
                isinstance(e, requests.HTTPError)
                and e.response is not None
                and e.response.status_code < 500
                and e.response.status_code != 429
            ):
                # `from None`: the original exception carries the full URL, key included,
                # and would otherwise be printed with the traceback.
                raise FetchError(redact(str(e)), response=e.response) from None
            wait = 2**attempt
            log.warning("%s 失敗（%s），%ds 後重試", url, redact(str(e)), wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _get(url: str, params: dict, retries: int = 4) -> dict:
    return _request(url, params, retries).json()


def rebuild_abstract(inverted: dict[str, list[int]] | None) -> str:
    if not inverted:
        return ""
    positions = [(i, word) for word, idxs in inverted.items() for i in idxs]
    return " ".join(word for _, word in sorted(positions))


def strip_jats(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def normalize_doi(doi: str | None) -> str:
    if not doi:
        return ""
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", doi.strip(), flags=re.I).lower()


def lookup_issn(name: str, api_key: str) -> list[tuple[str, str]]:
    """Return candidate (display_name, issn_l) pairs for a journal name."""
    data = _get(f"{OPENALEX}/sources", {"search": name, "per-page": 5, "api_key": api_key})
    return [(s["display_name"], s.get("issn_l") or "") for s in data.get("results", [])]


def parse_work(w: dict, journal_name: str) -> Article | None:
    doi = normalize_doi(w.get("doi"))
    title = w.get("title")
    if not doi or not title or w.get("type") in ("erratum", "retraction") or NOTICE_TITLE.match(title):
        return None
    authors = [
        a["author"]["display_name"]
        for a in w.get("authorships", [])
        if a.get("author", {}).get("display_name")
    ]
    landing = (w.get("primary_location") or {}).get("landing_page_url") or f"https://doi.org/{doi}"
    return Article(
        doi=doi,
        title=strip_jats(title),
        journal=journal_name,
        published=w.get("publication_date") or "",
        abstract=rebuild_abstract(w.get("abstract_inverted_index")),
        authors=authors,
        url=landing,
    )


def fetch_journal(issn: str, journal_name: str, since: date, api_key: str) -> list[Article]:
    params = {
        "filter": f"primary_location.source.issn:{issn},from_publication_date:{since.isoformat()},type:!erratum",
        "select": FIELDS,
        "per-page": 200,
        "cursor": "*",
        "api_key": api_key,
    }
    articles = []
    while True:
        data = _get(f"{OPENALEX}/works", params)
        for w in data.get("results", []):
            if a := parse_work(w, journal_name):
                articles.append(a)
        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor or not data.get("results"):
            break
        params["cursor"] = cursor
    return articles


def _clean_abstract(text: str) -> str:
    return re.sub(r"^Abstract\s+", "", strip_jats(text))


def _crossref_abstract(doi: str) -> str:
    data = _get(f"{CROSSREF}/works/{doi}", {}, retries=2)
    return data.get("message", {}).get("abstract") or ""


META_TAG = re.compile(r"<meta\b[^>]*>", re.I)
META_ATTR = re.compile(r"""\b(name|content)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)
ABSTRACT_META = ("citation_abstract", "dc.description")


def meta_abstract(page: str) -> str:
    """Pull the abstract out of a publisher landing page's <meta> tags (Nature, Wiley, T&F…)."""
    found = {}
    for tag in META_TAG.findall(page):
        attrs = {k.lower(): a or b for k, a, b in META_ATTR.findall(tag)}
        if attrs.get("content"):
            found.setdefault(attrs.get("name", "").lower(), attrs["content"])
    return next((found[n] for n in ABSTRACT_META if n in found), "")


def _landing_abstract(doi: str) -> str:
    return meta_abstract(_request(f"https://doi.org/{doi}", {}, retries=2).text)


def fill_abstract(article: Article) -> None:
    """Try Crossref, then the publisher's landing page."""
    sources = [("Crossref", lambda: _crossref_abstract(article.doi))]
    if not article.doi.startswith("10.1016/"):  # Elsevier: ScienceDirect refuses scripted requests
        sources.append(("出版社頁面", lambda: _landing_abstract(article.doi)))
    for name, source in sources:
        try:
            abstract = _clean_abstract(source())
        except (requests.RequestException, ValueError) as e:
            log.debug("%s %s 失敗：%s", name, article.doi, e)
            continue
        if abstract:
            article.abstract = abstract
            return
