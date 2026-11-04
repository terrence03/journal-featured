from journal_featured.fetch import normalize_doi, parse_work, rebuild_abstract, strip_jats


def test_rebuild_abstract_orders_words():
    assert rebuild_abstract({"world": [1], "hello": [0], "again": [2]}) == "hello world again"
    assert rebuild_abstract(None) == ""


def test_normalize_doi():
    assert normalize_doi("https://doi.org/10.1038/ABC") == "10.1038/abc"
    assert normalize_doi(None) == ""


def test_strip_jats():
    assert strip_jats("<jats:p>A &amp; B</jats:p>") == "A & B"


def test_parse_work():
    w = {
        "doi": "https://doi.org/10.1/x",
        "title": "T",
        "publication_date": "2026-10-01",
        "abstract_inverted_index": {"abc": [0]},
        "authorships": [{"author": {"display_name": "Lin"}}],
        "primary_location": {"landing_page_url": "https://example.org/x"},
    }
    a = parse_work(w, "J")
    assert (a.doi, a.abstract, a.authors, a.url) == ("10.1/x", "abc", ["Lin"], "https://example.org/x")
    assert parse_work({**w, "doi": None}, "J") is None


def test_parse_work_skips_notices():
    w = {"doi": "10.1/x", "title": "Author Correction: Something"}
    assert parse_work(w, "J") is None
    assert parse_work({"doi": "10.1/y", "title": "Real paper", "type": "erratum"}, "J") is None
    assert parse_work({"doi": "10.1/z", "title": "Correctional facilities and health"}, "J") is not None
