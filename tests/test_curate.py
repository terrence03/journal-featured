from types import SimpleNamespace

from journal_featured import curate
from journal_featured.fetch import Article


def _art(doi):
    return Article(doi=doi, title=f"T{doi}", journal="J", published="2026-10-01", abstract="", matches=["A"])


class FakeClient:
    def __init__(self, picks, stop_reason="end_turn", notes=()):
        self.calls = []
        parsed = curate.Curation(
            notes=[curate.Note(doi=d, note=n) for d, n in notes],
            featured=[curate.Pick(doi=d, reason=r) for d, r in picks],
        ) if picks is not None else None
        self.response = SimpleNamespace(
            parsed_output=parsed, stop_reason=stop_reason, model="claude-opus-5-5",
            usage=SimpleNamespace(input_tokens=100, output_tokens=10),
        )
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_curate_maps_dois_and_drops_unknown(monkeypatch):
    fake = FakeClient([("10.1/B", "理由B"), ("10.9/zzz", "幻覺"), ("10.1/a", "理由A")],
                      notes=[("10.1/a", "簡評A"), ("10.1/C", "簡評C"), ("10.9/zzz", "x")])
    monkeypatch.setattr(curate.anthropic, "Anthropic", lambda **kw: fake)
    arts = [_art("10.1/a"), _art("10.1/b"), _art("10.1/c")]
    result = curate.curate(arts, "interests", 2, "claude-opus-5-5", "medium")
    assert [(a.doi, r) for a, r in result] == [("10.1/b", "理由B"), ("10.1/a", "理由A")]
    assert [a.note for a in arts] == ["簡評A", "", "簡評C"]
    call = fake.calls[0]
    assert call["output_format"] is curate.Curation
    assert "10.1/c" in call["messages"][0]["content"]
    assert "（無摘要）" in call["messages"][0]["content"]


def test_curate_skips_when_too_few_candidates(monkeypatch):
    monkeypatch.setattr(curate.anthropic, "Anthropic", lambda **kw: (_ for _ in ()).throw(AssertionError))
    assert curate.curate([_art("1"), _art("2")], "x", 2, "m", "medium") == []


def test_curate_handles_refusal(monkeypatch):
    monkeypatch.setattr(curate.anthropic, "Anthropic", lambda **kw: FakeClient(None, "refusal"))
    assert curate.curate([_art(str(i)) for i in range(3)], "x", 2, "m", "medium") == []
