"""Render the digest email and send it via SMTP."""

import smtplib
import ssl
from contextlib import contextmanager
from email.message import EmailMessage

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import ROOT, Smtp
from .fetch import Article

_env = Environment(
    loader=FileSystemLoader(ROOT / "templates"),
    autoescape=select_autoescape(["html"]),
)


def _truncate(text: str, n: int = 400) -> str:
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


_env.filters["truncate_words"] = _truncate


def render(groups: dict[str, list[Article]], since: str, until: str,
           featured: list[tuple[Article, str]] | None = None) -> tuple[str, str]:
    """Return (html, plain_text)."""
    featured = featured or []
    html = _env.get_template("digest.html").render(
        groups=groups, since=since, until=until, featured=featured)
    lines = [f"期刊選讀 {since} ~ {until}", ""]
    if featured:
        lines.append("## 本週精選")
        for a, reason in featured:
            lines.append(f"- {a.title}")
            lines.append(f"  {a.journal}｜{a.published}｜{a.url}")
            lines.append(f"  {reason}")
        lines.append("")
    if not groups:
        lines.append("本期沒有符合議題的新文章。")
    for topic, articles in groups.items():
        lines.append(f"## {topic}")
        for a in articles:
            lines.append(f"- [{a.scores.get(topic, a.score):.2f}] {a.title}")
            if a.note:
                lines.append(f"  → {a.note}")
            lines.append(f"  {a.journal}｜{a.published}｜{a.url}")
        lines.append("")
    return html, "\n".join(lines)


def send(smtp: Smtp, recipients: list[str], subject: str, html: str, text: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp.user
    msg["To"] = ", ".join(recipients)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    with _connect(smtp) as s:
        s.send_message(msg)


def check(smtp: Smtp) -> None:
    """Log in without sending anything; raises on bad host, port or credentials."""
    with _connect(smtp):
        pass


@contextmanager
def _connect(smtp: Smtp):
    ctx = ssl.create_default_context()
    if smtp.port == 465:
        with smtplib.SMTP_SSL(smtp.host, smtp.port, context=ctx, timeout=30) as s:
            s.login(smtp.user, smtp.app_password)
            yield s
    else:
        with smtplib.SMTP(smtp.host, smtp.port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(smtp.user, smtp.app_password)
            yield s
