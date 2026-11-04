"""Ask Claude for a one-line note on every matched article and the few most worthwhile picks."""

import logging
import os

import anthropic
from pydantic import BaseModel, Field

from .fetch import Article

log = logging.getLogger(__name__)

SYSTEM = """你是一位能源經濟與能源政策領域的研究助理，替一位關注下列主題的讀者挑選每週必讀論文。

讀者的關注重點：
{interests}

你會收到本週經語意篩選後的候選論文（標題、期刊、摘要、符合的主題）。請完成兩件事：

一、notes：為每一篇候選論文各寫一句繁體中文簡評（40 字以內），說明它在研究什麼、
    與讀者哪個關注點相關，讓讀者掃一眼就能決定要不要點開。

二、featured：挑出最值得優先閱讀的 {n} 篇，標準依序為：
    1. 與讀者關注重點的直接相關程度
    2. 研究問題的政策意涵與重要性
    3. 方法或證據的扎實程度、是否提出新發現
    每篇以繁體中文寫 2–3 句推薦理由：說明這篇在研究什麼、為什麼值得讀。

只有標題、沒有摘要的論文，請依標題審慎判斷，不要臆測內容。"""


class Note(BaseModel):
    doi: str = Field(description="候選清單中該論文的 DOI，必須原樣照抄")
    note: str = Field(description="繁體中文一句簡評，40 字以內")


class Pick(BaseModel):
    doi: str = Field(description="候選清單中該論文的 DOI，必須原樣照抄")
    reason: str = Field(description="繁體中文推薦理由，2–3 句")


class Curation(BaseModel):
    # Notes first so the model reads every candidate before choosing.
    notes: list[Note] = Field(description="每一篇候選論文各一則")
    featured: list[Pick]


def _format(articles: list[Article]) -> str:
    parts = []
    for i, a in enumerate(articles, 1):
        parts.append(
            f"[{i}] DOI: {a.doi}\n"
            f"標題: {a.title}\n"
            f"期刊: {a.journal}（{a.published}）\n"
            f"符合主題: {'、'.join(a.matches)}\n"
            f"摘要: {a.abstract or '（無摘要）'}"
        )
    return "\n\n".join(parts)


def curate(articles: list[Article], interests: str, n: int, model: str, effort: str) -> list[tuple[Article, str]]:
    """Set .note on each article in place; return up to n featured (article, reason) pairs, best first."""
    if len(articles) <= n:
        return []
    # Keys not scoped to a workspace must name one on every request.
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    client = anthropic.Anthropic(default_headers={"anthropic-workspace-id": workspace} if workspace else None)
    response = client.beta.messages.parse(
        model=model,
        max_tokens=16000,
        system=SYSTEM.format(interests=interests.strip(), n=n),
        messages=[{"role": "user", "content": _format(articles)}],
        output_config={"effort": effort},
        output_format=Curation,
        # If the primary model declines, the API re-runs the request on a fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    u = response.usage
    log.info("Claude 精選：%s，輸入 %d / 輸出 %d tokens", response.model, u.input_tokens, u.output_tokens)
    if response.stop_reason == "refusal" or response.parsed_output is None:
        log.warning("Claude 未回傳精選結果（stop_reason=%s）", response.stop_reason)
        return []

    by_doi = {a.doi: a for a in articles}
    for item in response.parsed_output.notes:
        if a := by_doi.get(item.doi.strip().lower()):
            a.note = item.note.strip()
    if missing := sum(not a.note for a in articles):
        log.warning("%d 篇未取得簡評", missing)

    result = []
    for p in response.parsed_output.featured:
        if a := by_doi.get(p.doi.strip().lower()):
            result.append((a, p.reason.strip()))
        else:
            log.warning("Claude 回傳不在候選清單中的 DOI：%s", p.doi)
    return result[:n]
