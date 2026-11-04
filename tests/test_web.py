from journal_featured.web.common import bibtex, md


def test_md_escapes_markdown():
    assert md("A [b] *c* $5") == r"A \[b\] \*c\* \$5"


def test_bibtex_keys_are_unique():
    row = {"doi": "10.1/x", "title": "Solar {power} auctions", "journal": "J", "published": "2026-10-01",
           "authors": '["Ana Lin", "Bo Wu"]', "url": "https://doi.org/10.1/x"}
    out = bibtex([row, dict(row, doi="10.1/y")])
    assert "@article{lin2026solar," in out and "@article{lin2026solara," in out
    assert "author = {Ana Lin and Bo Wu}" in out
    assert "title = {Solar power auctions}" in out


def test_job_log_label():
    from pathlib import Path

    from journal_featured.web.jobs import describe
    assert describe(Path("20261103-080000-schedule.log")) == "11/03 08:00 · 排程執行"
    assert describe(Path("20261103-110105-curate_mail.log")) == "11/03 11:01 · 重新精選並寄信"
