"""Read-only web page for browsing the selected articles: `python -m journal_featured.web.app`.

A standard-library HTTP server rendering one Jinja2 template. Every link is a relative query
string (`?run=3`), so the page works unchanged behind a reverse proxy on any sub-path.
"""

import argparse
import logging
from contextlib import closing
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from journal_featured.config import ROOT
from journal_featured.db import Store
from journal_featured.fetch import Article
from journal_featured.schedule import DEFAULT, next_run

log = logging.getLogger(__name__)

PAGE_SIZE = 20
WEEKDAYS = "一二三四五六日"
HEADERS = {
    # No scripts, no external resources: the page is plain HTML + inline CSS.
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
                               "base-uri 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

_env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html"]))


def _url(**params) -> str:
    """Relative link carrying only the non-empty parameters."""
    return "?" + urlencode({k: v for k, v in params.items() if v})


def _http_url(url: str) -> str:
    """Article links come from external metadata: only http(s) may become an href."""
    return url if url.startswith(("https://", "http://")) else ""


def _authors(names: list[str]) -> str:
    return ", ".join(names[:3]) + (" et al." if len(names) > 3 else "")


_env.globals["url"] = _url
_env.filters["http_url"] = _http_url
_env.filters["authors"] = _authors


def _raw_config(path: Path) -> dict:
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _topic_counts(articles: list[Article], raw: dict) -> dict[str, int]:
    """Topics that have articles, in config order; topics since removed from the config come last."""
    names = [t["name"] for t in raw.get("topics") or [] if isinstance(t, dict) and t.get("name")]
    names += sorted({m for a in articles for m in a.matches} - set(names))
    counts = {n: sum(n in a.matches for a in articles) for n in names}
    return {n: c for n, c in counts.items() if c}


def _relevance(a: Article) -> float:
    return max((a.scores.get(m, a.score) for m in a.matches), default=a.score)


def _next_update(raw: dict) -> str:
    try:
        nxt = next_run(" ".join(str(raw.get("schedule") or DEFAULT).split()), datetime.now().astimezone())
    except (ValueError, TypeError):
        return ""
    return f"{nxt:%m/%d}（{WEEKDAYS[nxt.weekday()]}）{nxt:%H:%M}" if nxt else ""


def _issue(store: Store, runs: list[dict], raw: dict, params: dict) -> dict:
    """One run's selected articles: Claude's picks first, then the most relevant."""
    index = next((i for i, r in enumerate(runs) if str(r["id"]) == params.get("run")), 0)
    run = runs[index]
    articles = store.run_articles(run["id"])
    reasons = {a.doi: reason for a, reason in store.featured(run["id"], articles)}
    topics = _topic_counts(articles, raw)
    topic = params.get("topic") if params.get("topic") in topics else ""
    shown = [a for a in articles if not topic or topic in a.matches]
    order = list(reasons)
    shown.sort(key=lambda a: (order.index(a.doi) if a.doi in reasons else len(order), -_relevance(a)))
    return {
        "view": "issue", "run": run, "runs": runs, "latest": index == 0,
        "newer": runs[index - 1] if index > 0 else None,
        "older": runs[index + 1] if index + 1 < len(runs) else None,
        "topics": topics, "topic": topic, "total": len(articles),
        "articles": shown, "reasons": reasons,
    }


def _library(store: Store, runs: list[dict], raw: dict, params: dict) -> dict:
    """Every selected article across all runs, newest first, with keyword/topic/journal filters."""
    articles = [a for a in store.all_articles() if a.selected]
    topics = _topic_counts(articles, raw)
    journals = sorted({a.journal for a in articles})
    q = params.get("q", "")
    topic = params.get("topic") if params.get("topic") in topics else ""
    journal = params.get("journal") if params.get("journal") in journals else ""
    words = q.casefold().split()

    def keep(a: Article) -> bool:
        if topic and topic not in a.matches or journal and a.journal != journal:
            return False
        text = " ".join([a.title, a.abstract, a.note, a.journal, *a.authors]).casefold()
        return all(w in text for w in words)

    found = sorted(filter(keep, articles), key=lambda a: a.published, reverse=True)
    pages = max(1, -(-len(found) // PAGE_SIZE))
    page = params.get("page", "")
    page = min(int(page), pages) if page.isdigit() and int(page) > 0 else 1
    return {
        "view": "all", "runs": runs, "topics": topics, "journals": journals,
        "q": q, "topic": topic, "journal": journal, "total": len(found), "page": page, "pages": pages,
        "articles": found[(page - 1) * PAGE_SIZE:page * PAGE_SIZE],
        "reasons": {p["doi"]: p["reason"] for r in reversed(runs) for p in r["featured"]},
    }


def render(params: dict[str, str], config_path: Path | None = None) -> str:
    raw = _raw_config(config_path or ROOT / "config.yaml")
    with closing(Store(ROOT / raw.get("db_path", "data/journal.db"))) as store:
        runs = store.runs()
        if not runs:
            context = {"view": "empty", "runs": []}
        elif params.get("view") == "all":
            context = _library(store, runs, raw, params)
        else:
            context = _issue(store, runs, raw, params)
    return _env.get_template("web.html").render(**context, next_update=_next_update(raw))


class Handler(BaseHTTPRequestHandler):
    server_version = "journal-featured"

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        name = url.path.rstrip("/").rsplit("/", 1)[-1]
        if name == "healthz":
            return self._send(200, "ok", "text/plain")
        if "." in name:  # favicon.ico, robots.txt…: there are no static files
            return self._send(404, "not found", "text/plain")
        params = {k: v[-1].strip() for k, v in parse_qs(url.query).items()}
        try:
            body = render(params)
        except Exception:
            log.exception("無法產生頁面 %s", self.path)
            return self._send(500, "頁面暫時無法顯示，請稍後再試。", "text/plain")
        self._send(200, body, "text/html")

    do_HEAD = do_GET

    def _send(self, status: int, body: str, content_type: str) -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for k, v in HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        log.debug("%s %s", self.address_string(), format % args)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="期刊選讀網頁（唯讀）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    log.info("期刊選讀網頁：http://%s:%d", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
