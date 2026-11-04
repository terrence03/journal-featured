import numpy as np

from journal_featured.config import Topic
from journal_featured.fetch import Article
from journal_featured.score import assign, pick

TOPICS = [Topic("A", "a"), Topic("B", "b")]


def _art(doi):
    return Article(doi=doi, title=doi, journal="J", published="", abstract="")


def test_assign_and_pick():
    arts = [_art("1"), _art("2"), _art("3")]
    sims = np.array([[0.9, 0.1], [0.2, 0.85], [0.5, 0.6]])
    assign(arts, TOPICS, sims, threshold=0.8)
    assert [a.topic for a in arts] == ["A", "B", "B"]
    assert [a.matches for a in arts] == [["A"], ["B"], []]
    assert [a.selected for a in arts] == [True, True, False]
    groups = pick(arts, TOPICS, max_per_topic=10)
    assert {k: [a.doi for a in v] for k, v in groups.items()} == {"A": ["1"], "B": ["2"]}


def test_pick_limits_per_topic():
    arts = [_art(str(i)) for i in range(5)]
    assign(arts, TOPICS, np.array([[0.9 + i / 100, 0] for i in range(5)]), threshold=0.8)
    assert [a.doi for a in pick(arts, TOPICS, 2)["A"]] == ["4", "3"]


def test_topic_threshold_overrides_global():
    topics = [Topic("A", "a", threshold=0.95), Topic("B", "b")]
    arts = [_art("1"), _art("2")]
    assign(arts, topics, np.array([[0.9, 0.1], [0.1, 0.9]]), threshold=0.8)
    assert [a.selected for a in arts] == [False, True]


def test_article_can_match_several_topics():
    arts = [_art("1"), _art("2")]
    assign(arts, TOPICS, np.array([[0.82, 0.9], [0.95, 0.5]]), threshold=0.8)
    assert arts[0].matches == ["B", "A"]  # best first
    groups = pick(arts, TOPICS, max_per_topic=10)
    assert [a.doi for a in groups["A"]] == ["2", "1"]  # sorted by topic-A score
    assert [a.doi for a in groups["B"]] == ["1"]
