"""Weekly run: fetch → dedupe → score → log to SQLite → email digest."""

import argparse
import logging
import sys
from datetime import date, datetime, timedelta

from . import curate, fetch, lock, mailer, score
from .config import ConfigError, load
from .db import Store

log = logging.getLogger("journal_featured")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="期刊選讀：依議題篩選期刊新文章")
    p.add_argument("--dry-run", action="store_true", help="只抓取與評分並印出結果，不寫資料庫、不寄信")
    p.add_argument("--days", type=int, help="回溯天數（覆蓋 config 的 lookback_days）")
    p.add_argument("--no-email", action="store_true", help="寫資料庫但不寄信")
    p.add_argument("--lookup", metavar="NAME", help="查詢期刊名稱對應的 ISSN 後結束")
    p.add_argument("--resend", action="store_true",
                   help="不抓取、不呼叫 Claude，用資料庫中最近一次執行的入選文章與已存精選重寄信件")
    p.add_argument("--curate-only", action="store_true",
                   help="不重新抓取與評分，直接對資料庫中最近一次執行的入選文章做 Claude 精選")
    return p.parse_args(argv)


def resolve_issns(cfg) -> list[str]:
    errors = []
    for j in cfg.journals:
        if j.issn:
            continue
        candidates = fetch.lookup_issn(j.name, cfg.openalex_key)
        if candidates and candidates[0][1]:
            j.issn = candidates[0][1]
            log.warning("「%s」未設定 ISSN，暫用 %s（%s）；建議寫入 config.yaml", j.name, j.issn, candidates[0][0])
        else:
            errors.append(f"{j.name}: 找不到 ISSN")
    return errors


def fill_abstracts(articles: list[fetch.Article]) -> None:
    for a in articles:
        if not a.abstract:
            fetch.fill_abstract_from_crossref(a)
    log.info("摘要缺漏：%d / %d 篇", sum(not a.abstract for a in articles), len(articles))


def run_curate_only(args, cfg) -> int:
    """Re-use the latest run's matched articles from the DB instead of fetching and scoring again."""
    if not cfg.curate:
        raise ConfigError("未設定 ANTHROPIC_API_KEY 或 config.yaml 的 curate.enabled 為 false")
    store = Store(cfg.db_path)
    latest = store.latest_run()
    if not latest:
        raise ConfigError("資料庫中沒有任何執行紀錄，請先正常執行一次")
    run_id, since, until, articles = latest
    log.info("沿用第 %d 次執行（%s ~ %s）的 %d 篇入選文章", run_id, since, until, len(articles))

    missing = [a for a in articles if not a.abstract]
    fill_abstracts(missing)
    store.update_abstracts(missing)

    c = cfg.curate
    try:
        featured = curate.curate(articles, c.interests, c.picks, c.model, c.effort)
    except Exception as e:
        log.error("Claude 精選失敗：%s", e)
        store.close()
        return 1
    for a, reason in featured:
        print(f"\n◆ {a.title}\n  {a.journal}｜{a.published}｜{'、'.join(a.matches)}\n  {a.url}\n  {reason}")
    store.update_notes(articles)
    if not featured:
        log.warning("沒有產生精選結果")
        store.close()
        return 1
    store.set_featured(run_id, featured)

    if not args.no_email:
        groups = score.pick(articles, cfg.topics, cfg.max_per_topic)
        html, text = mailer.render(groups, since, until, featured)
        mailer.send(cfg.smtp, cfg.recipients, f"期刊選讀 {until}（含精選）：{len(articles)} 篇", html, text)
        log.info("已寄送 %d 人", len(cfg.recipients))
    store.close()
    return 0


def run_resend(cfg) -> int:
    store = Store(cfg.db_path)
    latest = store.latest_run()
    if not latest:
        raise ConfigError("資料庫中沒有任何執行紀錄")
    run_id, since, until, articles = latest
    featured = store.featured(run_id, articles)
    store.close()
    log.info("重寄第 %d 次執行（%s ~ %s）：%d 篇，精選 %d 篇", run_id, since, until, len(articles), len(featured))
    groups = score.pick(articles, cfg.topics, cfg.max_per_topic)
    html, text = mailer.render(groups, since, until, featured)
    suffix = "（含精選）" if featured else ""
    mailer.send(cfg.smtp, cfg.recipients, f"期刊選讀 {until}{suffix}：{len(articles)} 篇", html, text)
    log.info("已寄送 %d 人：%s", len(cfg.recipients), ", ".join(cfg.recipients))
    return 0


def run(args) -> int:
    use_db = not args.dry_run
    send_mail = not (args.dry_run or args.no_email)
    cfg = load(need_smtp=send_mail and not args.lookup)

    if args.lookup:
        for name, issn in fetch.lookup_issn(args.lookup, cfg.openalex_key):
            print(f"{issn or '(無)':<10} {name}")
        return 0

    with lock.hold(cfg.db_path.parent / lock.NAME):
        if args.resend:
            return run_resend(cfg)
        if args.curate_only:
            return run_curate_only(args, cfg)
        return run_pipeline(args, cfg, use_db, send_mail)


def run_pipeline(args, cfg, use_db: bool, send_mail: bool) -> int:
    now = datetime.now().astimezone()
    run_at = now.strftime("%Y-%m-%d %H:%M")
    until = now.date()
    since = until - timedelta(days=args.days or cfg.lookback_days)

    errors = resolve_issns(cfg)
    counts: dict[str, int] = {}
    articles: list[fetch.Article] = []
    for j in cfg.journals:
        if not j.issn:
            continue
        try:
            found = fetch.fetch_journal(j.issn, j.name, since, cfg.openalex_key)
        except Exception as e:
            log.exception("抓取 %s 失敗", j.name)
            errors.append(f"{j.name}: {e}")
            continue
        counts[j.name] = len(found)
        articles.extend(found)
        log.info("%s：%d 篇", j.name, len(found))

    # Same DOI can appear under multiple ISSNs; keep first.
    unique: dict[str, fetch.Article] = {}
    for a in articles:
        unique.setdefault(a.doi, a)
    articles = list(unique.values())

    store = None
    if use_db:
        store = Store(cfg.db_path)
        seen = store.seen_dois()
        articles = [a for a in articles if a.doi not in seen]
    log.info("待評分新文章：%d 篇", len(articles))

    fill_abstracts(articles)

    score.score(articles, cfg.topics, cfg.model, cfg.threshold)
    groups = score.pick(articles, cfg.topics, cfg.max_per_topic)
    matched = list({a.doi: a for v in groups.values() for a in v}.values())
    n_selected = len(matched)

    featured: list[tuple[fetch.Article, str]] = []
    if cfg.curate and (send_mail or args.dry_run):
        c = cfg.curate
        try:
            featured = curate.curate(matched, c.interests, c.picks, c.model, c.effort)
        except Exception as e:
            log.exception("Claude 精選失敗，信件將不含精選區塊")
            errors.append(f"curate: {e}")
    elif not cfg.curate:
        log.info("未設定 ANTHROPIC_API_KEY 或已停用精選，略過 Claude 精選")

    if args.dry_run:
        for t in cfg.topics:
            ranked = sorted(articles, key=lambda a: a.scores.get(t.name, 0), reverse=True)
            n = sum(t.name in a.matches for a in articles)
            print(f"\n== {t.name}（門檻 {t.threshold or cfg.threshold}，入選 {n} 篇）")
            for a in ranked[:8]:
                mark = "★" if t.name in a.matches else " "
                print(f"{mark} {a.scores[t.name]:.3f}  {a.title[:90]}  ({a.journal})")
        print(f"\n共 {len(articles)} 篇，入選 {n_selected} 篇")
        for a, reason in featured:
            print(f"\n◆ 本週精選：{a.title}（{a.journal}）\n  {reason}")
        if errors:
            print("錯誤：", *errors, sep="\n  ")
        return 0

    mail_status = "未寄送"
    if send_mail and (groups or cfg.send_empty):
        html, text = mailer.render(groups, since.isoformat(), until.isoformat(), featured)
        subject = f"期刊選讀 {until.isoformat()}：{n_selected} 篇"
        try:
            mailer.send(cfg.smtp, cfg.recipients, subject, html, text)
            mail_status = f"已寄送 {len(cfg.recipients)} 人"
        except Exception as e:
            log.exception("寄信失敗")
            mail_status = "寄送失敗"
            errors.append(f"email: {e}")

    store.save_run(articles, run_at, since.isoformat(), until.isoformat(), counts,
                   n_selected, mail_status, errors, featured)
    store.close()
    log.info("完成：新文章 %d、入選 %d、%s", len(articles), n_selected, mail_status)
    return 1 if errors else 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("httpx", "httpx2"):  # huggingface_hub logs every model-file request
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        return run(parse_args(argv))
    except ConfigError as e:
        log.error("設定錯誤：%s", e)
        return 2
    except lock.Busy as e:
        log.error("%s，本次略過", e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
