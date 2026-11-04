"""Load config.yaml and secrets from .env, failing early with clear messages."""

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from io import StringIO
from pathlib import Path

import yaml
from dotenv import load_dotenv, set_key

ROOT = Path(__file__).resolve().parents[2]
# API keys and SMTP settings, entered in the web UI (or by hand). Kept out of config.yaml so they
# never land in its backups; .env is only for docker compose variables (WEB_BIND, TZ).
SECRETS = ROOT / "data" / "secrets.env"
SECRET_KEYS = ("OPENALEX_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID",
               "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_APP_PASSWORD")


class ConfigError(Exception):
    pass


@dataclass
class Journal:
    name: str
    issn: str | None = None


@dataclass
class Topic:
    name: str
    description: str
    threshold: float | None = None  # overrides the global threshold


@dataclass
class Curate:
    enabled: bool
    picks: int
    model: str
    effort: str
    interests: str


@dataclass
class Smtp:
    host: str
    port: int
    user: str
    app_password: str


@dataclass
class Config:
    db_path: Path
    lookback_days: int
    threshold: float
    max_per_topic: int
    send_empty: bool
    model: str
    recipients: list[str]
    journals: list[Journal]
    topics: list[Topic]
    openalex_key: str
    curate: Curate | None = None  # None: disabled or no ANTHROPIC_API_KEY
    smtp: Smtp | None = field(default=None)


def load_secrets(path: Path | None = None) -> None:
    """Load API keys and SMTP settings from data/secrets.env, the single place they live."""
    path = path or SECRETS
    if path.exists():
        load_dotenv(path, override=True)


def save_secrets(values: dict[str, str], path: Path | None = None) -> None:
    path = path or SECRETS
    unknown = set(values) - set(SECRET_KEYS)
    if unknown:
        raise ValueError(f"unknown keys: {unknown}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    for k, v in values.items():
        set_key(path, k, v, quote_mode="always")
        os.environ[k] = v


def _env(*names: str) -> dict[str, str]:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise ConfigError(f"缺少：{', '.join(missing)}（請到網頁介面「API 與寄信」填寫，存於 data/secrets.env）")
    return {n: os.environ[n] for n in names}


def _require(d: dict, keys: list[str], where: str) -> None:
    missing = [k for k in keys if not d.get(k)]
    if missing:
        raise ConfigError(f"{where} 缺少欄位：{', '.join(missing)}")


def _curate(raw: dict, topics: list[Topic]) -> Curate | None:
    if not raw.get("enabled", True) or not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    interests = raw.get("interests") or "\n".join(f"- {t.name}：{t.description}" for t in topics)
    return Curate(
        enabled=True,
        picks=int(raw.get("picks", 2)),
        model=raw.get("model", "claude-opus-5-5"),
        effort=raw.get("effort", "medium"),
        interests=interests,
    )


ISSN = re.compile(r"^\d{4}-\d{3}[\dX]$", re.I)


def validate_raw(raw: dict, where: str = "config.yaml") -> tuple[list[Journal], list[Topic]]:
    """Check the config structure (no .env needed); raise ConfigError listing every problem."""
    _require(raw, ["journals", "topics"], where)
    errors = []

    def unit(v, label):
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 < v < 1:
            errors.append(f"{label} 需為 0 到 1 之間的數字")

    def positive_int(key):
        v = raw.get(key)
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 1):
            errors.append(f"{key} 需為正整數")

    journals, topics = [], []
    for i, j in enumerate(raw["journals"], 1):
        if not isinstance(j, dict) or not j.get("name"):
            errors.append(f"第 {i} 個期刊缺少 name")
            continue
        if j.get("issn") and not ISSN.match(str(j["issn"])):
            errors.append(f"期刊「{j['name']}」的 ISSN 格式應為 1234-567X")
        journals.append(Journal(name=j["name"], issn=j.get("issn")))
    for i, t in enumerate(raw["topics"], 1):
        if not isinstance(t, dict) or not t.get("name") or not t.get("description"):
            errors.append(f"第 {i} 個議題缺少 name 或 description")
            continue
        if t.get("threshold") is not None:
            unit(t["threshold"], f"議題「{t['name']}」的 threshold")
        topics.append(Topic(name=t["name"], description=t["description"], threshold=t.get("threshold")))
    names = [t.name for t in topics]
    if dupes := sorted({n for n in names if names.count(n) > 1}):
        errors.append(f"議題名稱重複：{'、'.join(dupes)}")

    if "threshold" in raw:
        unit(raw["threshold"], "threshold")
    if raw.get("schedule") is not None:
        from .schedule import CRON
        if not CRON.match(" ".join(str(raw["schedule"]).split())):
            errors.append("schedule 需為 5 欄 cron 格式，如 \"0 8 * * 1\"")
    positive_int("lookback_days")
    positive_int("max_per_topic")
    for r in raw.get("recipients") or []:
        if not isinstance(r, str) or "@" not in r:
            errors.append(f"收件人格式錯誤：{r}")
    c = raw.get("curate") or {}
    if c.get("effort", "medium") not in ("low", "medium", "high"):
        errors.append("curate.effort 需為 low / medium / high")
    if (p := c.get("picks", 2)) is not None and (not isinstance(p, int) or isinstance(p, bool) or p < 0):
        errors.append("curate.picks 需為非負整數")

    if errors:
        raise ConfigError("；".join(errors))
    return journals, topics


def _yaml_rt():
    from ruamel.yaml import YAML
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _merge(old, new):
    """Update a ruamel round-trip node in place so comments and key order survive."""
    from ruamel.yaml.scalarstring import LiteralScalarString

    def value(v):
        return LiteralScalarString(v) if isinstance(v, str) and "\n" in v else v

    if isinstance(old, dict) and isinstance(new, dict):
        for k in [k for k in old if k not in new]:
            del old[k]
        for k, v in new.items():
            if k in old and isinstance(old[k], (dict, list)) and type(v) in (dict, list) \
                    and isinstance(old[k], type(v)):
                _merge(old[k], v)
            elif k not in old or old[k] != v:
                old[k] = value(v)
        return old
    if isinstance(old, list) and isinstance(new, list):
        if _named(old) and _named(new):
            return _merge_named(old, new, value)
        for i, v in enumerate(new):
            if i >= len(old):
                old.append(value(v))
            elif isinstance(old[i], (dict, list)) and isinstance(old[i], type(v)):
                _merge(old[i], v)
            elif old[i] != v:
                old[i] = value(v)
        del old[len(new):]
        return old
    return new


def _named(items: list) -> bool:
    names = [i.get("name") for i in items if isinstance(i, dict)]
    return len(names) == len(items) and all(names) and len(set(names)) == len(names)


def _merge_named(old, new, value):
    """Match list items by `name`, so deleting or reordering journals/topics keeps each item's
    comments with it. A deleted item's trailing comment (e.g. the next section's heading) moves
    to the closest surviving item before it."""
    by_name = {o["name"]: o for o in old}
    keep = {v["name"] for v in new}
    survivor = None
    for o in list(old):
        if o["name"] in keep:
            survivor = o
        elif survivor is not None and o:
            _move_trailing_comment(o, survivor)
    result = [_merge(by_name[v["name"]], v) if v["name"] in by_name else value(v) for v in new]
    del old[:]
    old.extend(result)
    return old


def _move_trailing_comment(src, dst) -> None:
    src_tok = src.ca.items.get(list(src)[-1])
    if not src_tok or len(src_tok) < 3 or src_tok[2] is None:
        return
    last = list(dst)[-1]
    dst_tok = dst.ca.items.setdefault(last, [None, None, None, None])
    if dst_tok[2] is None:
        dst_tok[2] = src_tok[2]


def save_raw(raw: dict, config_path: Path | None = None, backup_dir: Path | None = None,
             keep: int = 20) -> Path | None:
    """Validate and write `raw` back to config.yaml, keeping comments; return the backup path.

    The file is rewritten in place (not renamed over) because Docker bind-mounts it as a single
    file: replacing the inode would leave other containers reading the old version.
    """
    config_path = config_path or ROOT / "config.yaml"
    validate_raw(raw, str(config_path))
    y = _yaml_rt()
    original = config_path.read_text()
    doc = _merge(y.load(original), raw)
    buf = StringIO()
    y.dump(doc, buf)
    if yaml.safe_load(buf.getvalue()) != raw:  # guard against a merge bug corrupting the config
        raise ConfigError("寫回結果與預期不符，已取消儲存")

    backup = None
    if backup_dir:
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"config-{datetime.now():%Y%m%d-%H%M%S}.yaml"
        backup.write_text(original)
        for old in sorted(backup_dir.glob("config-*.yaml"))[:-keep]:
            old.unlink()
    with config_path.open("r+") as f:
        f.seek(0)
        f.write(buf.getvalue())
        f.truncate()
    return backup


def load(config_path: Path | None = None, need_smtp: bool = True) -> Config:
    config_path = config_path or ROOT / "config.yaml"
    raw = yaml.safe_load(config_path.read_text()) or {}
    journals, topics = validate_raw(raw, str(config_path))

    load_secrets()
    api = _env("OPENALEX_API_KEY")

    smtp = None
    if need_smtp:
        s = _env("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_APP_PASSWORD")
        smtp = Smtp(host=s["SMTP_HOST"], port=int(s["SMTP_PORT"]),
                    user=s["SMTP_USER"], app_password=s["SMTP_APP_PASSWORD"])
        if not raw.get("recipients"):
            raise ConfigError("config.yaml 未設定 recipients")

    return Config(
        db_path=ROOT / raw.get("db_path", "data/journal.db"),
        lookback_days=int(raw.get("lookback_days", 14)),
        threshold=float(raw.get("threshold", 0.85)),
        max_per_topic=int(raw.get("max_per_topic", 10)),
        send_empty=bool(raw.get("send_empty", True)),
        model=raw.get("model", "intfloat/multilingual-e5-base"),
        recipients=list(raw.get("recipients") or []),
        journals=journals,
        topics=topics,
        openalex_key=api["OPENALEX_API_KEY"],
        curate=_curate(raw.get("curate") or {}, topics),
        smtp=smtp,
    )
