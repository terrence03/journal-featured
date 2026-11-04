"""Score articles against topics by embedding cosine similarity."""

import logging

from .config import Topic
from .fetch import Article

log = logging.getLogger(__name__)


def _prefixes(model_name: str) -> tuple[str, str]:
    # E5 models are trained with these prefixes; other models don't need them.
    if "e5" in model_name.lower():
        return "query: ", "passage: "
    return "", ""


def score(articles: list[Article], topics: list[Topic], model_name: str, threshold: float) -> None:
    """Set topic/score/scores/matches/selected on each article in place."""
    if not articles:
        return
    from sentence_transformers import SentenceTransformer

    log.info("載入 embedding 模型 %s", model_name)
    model = SentenceTransformer(model_name)
    q, p = _prefixes(model_name)
    topic_vecs = model.encode([q + t.description for t in topics], normalize_embeddings=True)
    article_vecs = model.encode(
        [p + a.text for a in articles], normalize_embeddings=True, batch_size=32
    )
    sims = article_vecs @ topic_vecs.T
    assign(articles, topics, sims, threshold)


def assign(articles: list[Article], topics: list[Topic], sims, threshold: float) -> None:
    """An article matches every topic whose threshold it passes, not just its best one."""
    for a, row in zip(articles, sims):
        a.scores = {t.name: round(float(s), 4) for t, s in zip(topics, row)}
        a.topic, a.score = max(a.scores.items(), key=lambda kv: kv[1])
        a.matches = sorted(
            (t.name for t in topics
             if a.scores[t.name] >= (t.threshold if t.threshold is not None else threshold)),
            key=lambda name: a.scores[name], reverse=True,
        )
        a.selected = bool(a.matches)


def pick(articles: list[Article], topics: list[Topic], max_per_topic: int) -> dict[str, list[Article]]:
    """Group matched articles under each topic (config order), highest topic score first.

    An article matching several topics appears under each of them.
    """
    groups = {}
    for t in topics:
        matched = [a for a in articles if t.name in a.matches]
        matched.sort(key=lambda a: a.scores.get(t.name, a.score), reverse=True)
        if matched:
            groups[t.name] = matched[:max_per_topic]
    return groups
