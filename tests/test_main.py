from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from journal_featured import main


def _setup(monkeypatch, tmp_path, pipeline):
    sent = []
    cfg = SimpleNamespace(db_path=Path(tmp_path) / "journal.db", smtp=object(), recipients=["a@b.c"])

    @contextmanager
    def hold(path):
        yield

    monkeypatch.setattr(main, "load", lambda need_smtp=True: cfg)
    monkeypatch.setattr(main.lock, "hold", hold)
    monkeypatch.setattr(main, "run_pipeline", pipeline)
    monkeypatch.setattr(main.mailer, "send", lambda smtp, to, subject, html, text: sent.append((subject, html, text)))
    return sent


def _crash(*a):
    raise RuntimeError("boom <x> https://api.openalex.org/works?api_key=SECRET123")


def test_crash_sends_failure_notice(monkeypatch, tmp_path):
    sent = _setup(monkeypatch, tmp_path, _crash)
    assert main.main([]) == 1
    (subject, html, text), = sent
    assert "執行失敗" in subject and "RuntimeError: boom" in text
    assert "SECRET123" not in text + html and "&lt;x&gt;" in html


def test_crash_without_email_stays_quiet(monkeypatch, tmp_path):
    sent = _setup(monkeypatch, tmp_path, _crash)
    assert main.main(["--no-email"]) == 1
    assert sent == []
