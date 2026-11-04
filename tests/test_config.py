import pytest
import yaml

from journal_featured.config import ConfigError, save_raw, validate_raw

CONFIG = """\
# 標頭註解
threshold: 0.85            # 全域門檻
recipients:
  - a@example.com

curate:
  enabled: true
  interests: |
    - 第一點
    - 第二點

journals:
  # 第一組
  - name: A
    issn: 0140-9883
  - name: B
    issn: 0195-6574
  # 第二組
  - name: C
    issn: 0301-4215

# 議題區塊說明
topics:
  - name: T1
    description: "energy transition"
    threshold: 0.83
  - name: T2
    description: "renewables"
"""


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(CONFIG)
    return p


def test_unchanged_save_is_byte_identical(cfg, tmp_path):
    backup = save_raw(yaml.safe_load(CONFIG), cfg, tmp_path / "bak")
    assert cfg.read_text() == CONFIG
    assert backup.read_text() == CONFIG


def test_edits_keep_comments(cfg):
    raw = yaml.safe_load(CONFIG)
    raw["threshold"] = 0.8
    raw["journals"] = [j for j in raw["journals"] if j["name"] != "B"]  # B carries "# 第二組"
    raw["topics"][1]["threshold"] = 0.81
    del raw["topics"][0]["threshold"]
    raw["topics"].append({"name": "T3", "description": "subsidies"})
    raw["curate"]["interests"] += "- 第三點\n"
    save_raw(raw, cfg)
    out = cfg.read_text()
    assert yaml.safe_load(out) == raw
    for comment in ("# 標頭註解", "# 全域門檻", "# 第一組", "# 第二組", "# 議題區塊說明"):
        assert comment in out
    assert out.index("# 第二組") < out.index("name: C")
    assert "interests: |" in out


def test_reorder_moves_items_with_values(cfg):
    raw = yaml.safe_load(CONFIG)
    raw["topics"].reverse()
    save_raw(raw, cfg)
    assert [t["name"] for t in yaml.safe_load(cfg.read_text())["topics"]] == ["T2", "T1"]


def test_invalid_config_is_not_written(cfg, tmp_path):
    raw = yaml.safe_load(CONFIG)
    raw["topics"].append({"name": "T1", "description": "dupe", "threshold": 1.5})
    raw["journals"][0]["issn"] = "123"
    with pytest.raises(ConfigError) as e:
        save_raw(raw, cfg, tmp_path / "bak")
    assert "重複" in str(e.value) and "ISSN" in str(e.value) and "threshold" in str(e.value)
    assert cfg.read_text() == CONFIG
    assert not (tmp_path / "bak").exists()


def test_backups_are_pruned(cfg, tmp_path):
    bak = tmp_path / "bak"
    bak.mkdir()
    for i in range(5):
        (bak / f"config-2026010{i}-000000.yaml").write_text("x")
    save_raw(yaml.safe_load(CONFIG), cfg, bak, keep=3)
    assert len(list(bak.glob("config-*.yaml"))) == 3


def test_validate_raw_accepts_example_config():
    from journal_featured.config import ROOT
    journals, topics = validate_raw(yaml.safe_load((ROOT / "config.example.yaml").read_text()))
    assert journals and topics


def test_secrets_override_env_and_roundtrip(tmp_path, monkeypatch):
    import os
    import stat

    from journal_featured.config import load_secrets, save_secrets
    path = tmp_path / "data" / "secrets.env"
    monkeypatch.setenv("SMTP_USER", "from-dotenv@example.com")
    monkeypatch.delenv("SMTP_APP_PASSWORD", raising=False)
    save_secrets({"SMTP_USER": "ui@example.com", "SMTP_APP_PASSWORD": "abcd efgh 'ijkl'"}, path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    monkeypatch.setenv("SMTP_USER", "from-dotenv@example.com")  # as if a fresh process read .env
    load_secrets(path)
    assert os.environ["SMTP_USER"] == "ui@example.com"
    assert os.environ["SMTP_APP_PASSWORD"] == "abcd efgh 'ijkl'"
    with pytest.raises(ValueError):
        save_secrets({"PATH": "/evil"}, path)
