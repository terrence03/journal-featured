# journal-featured 期刊選讀

每週從指定期刊抓新文章（OpenAlex），以 embedding 語意相似度比對感興趣主題，
查詢紀錄存入 SQLite（`data/journal.db`），入選文章以 Email 寄出。

## 設定
1. `config.yaml`：先 `cp config.example.yaml config.yaml`（此檔含收件人等個人設定，不進 git；一定要在 `docker compose up` 前建立，否則 Docker 會把它建成資料夾）；期刊（名稱 + ISSN）、主題（名稱 + 一段描述）、門檻、收件人、排程 `schedule`、`db_path`
   - 查 ISSN：`uv run journal-featured --lookup "期刊名稱"`
2. `data/secrets.env`：API 金鑰與寄信設定，手動建立（`chmod 600`）：
   ```
   OPENALEX_API_KEY=...
   ANTHROPIC_API_KEY=...          # 選填，Claude 精選
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=you@gmail.com
   SMTP_APP_PASSWORD=...          # Gmail 應用程式密碼：https://myaccount.google.com/apppasswords
   ```
3. `.env`（選填）：只用來覆蓋部署變數 `JOURNAL_WEB_BIND`、`JOURNAL_WEB_PORT`、`TZ`，見 `.env.example`

設定位置只有一條規則：**金鑰在 `data/secrets.env`，其餘都在 `config.yaml`**。

## 執行（Docker Compose）
程式只在容器裡執行，本機不需要 Python 環境。

```bash
docker compose build                    # 建置映像檔（內含 CPU 版 torch 與 embedding 模型）
docker compose up -d                    # 啟動常駐服務，依 config.yaml 的 schedule 排程執行
docker compose logs -f                  # 查看 log

# 單次執行（不影響常駐服務）
docker compose run --rm app journal-featured --lookup "期刊名稱"
docker compose run --rm app journal-featured --dry-run --days 30   # 只抓取評分並印出，用來校準門檻
docker compose run --rm app journal-featured --no-email            # 寫資料庫不寄信
docker compose run --rm app journal-featured                       # 立即正式執行一次
```

- `config.yaml` 以唯讀方式掛載，修改後下次執行就生效，不需重建
- 修改程式碼或 `pyproject.toml` 後需 `docker compose up -d --build`
- 排程在 `config.yaml` 的 `schedule`（cron 格式，預設 `0 8 * * 1` 每週一 08:00），修改後約 30 秒內自動生效，不需重啟；時區用 `.env` 的 `TZ` 覆蓋（預設 Asia/Taipei）
- 若 `config.yaml` 換了 `model`，第一次執行時會下載並快取在 `hf-cache` volume；或用 `docker compose build --build-arg MODEL=...` 直接打包進映像檔

## 網頁
`docker compose up -d` 會同時啟動 `web` 服務，開啟 http://127.0.0.1:8501 。網頁只用來閱讀，不能修改任何設定：

- **每期選讀**：一期一頁，Claude 精選（附推薦理由）排最前，其餘依相關程度排列；每篇有期刊、日期、作者、
  一句簡評，摘要點開才顯示；可用主題標籤篩選，並切換上一期／下一期
- **全部文章**：歷來所有入選文章，可用關鍵字（標題、摘要、作者）、主題、期刊搜尋

說明：
- `web` 與 `app` 共用同一映像檔；`web` 是標準函式庫的 HTTP 伺服器 + 一個 Jinja2 範本（`templates/web.html`），沒有 JavaScript
- 預設只綁定本機；要從其他電腦連線可在 `.env` 設 `JOURNAL_WEB_BIND=0.0.0.0`（網頁沒有登入機制，請只在可信任的網路使用）
- 頁面連結全為相對路徑，放在反向代理（如 `tailscale serve`）的任何子路徑下都不需額外設定
- 排程與手動執行（`docker compose run`）以 `data/run.lock` 互斥，同時只會有一個在跑（另一個會以代碼 3 略過）
- 直接在主機上編輯 `config.yaml` 時，請用會就地寫入的編輯器；若編輯器以新檔取代原檔，容器內仍會看到舊版，需 `docker compose restart`
- 不用 Docker 時：`uv run python -m journal_featured.web.app`

## Claude 精選
由 Claude（預設 Opus 5.5）依 `config.yaml` 的 `curate.interests`，一次呼叫完成：
- 每篇入選文章一句繁中簡評，顯示在信中標題下方，存入 `articles.note`
- 挑出 `picks` 篇（預設 2）附 2–3 句推薦理由，放在信件最上方，存入 `runs.featured`

- 未設定 `ANTHROPIC_API_KEY` 時自動略過，其餘流程照常
- 每次約 9k 輸入 + 3–4k 輸出 tokens，Opus 5.5 約 US$0.1
- 已啟用 server-side fallback：主模型拒答時，API 會自動改由其他模型處理
- `--dry-run` 也會呼叫 Claude 並印出精選結果（會計費）；`--no-email` 則不呼叫
- `--curate-only`：對資料庫中最近一次執行的入選文章重新精選（不重新抓取）
- `--resend`：用資料庫中已存的簡評與精選重寄信件，不呼叫 Claude

`--rescore`：以目前的主題描述與模型重新計算資料庫中所有文章的各主題分數，不改變各期的入選紀錄。

`--fill-abstracts`：為資料庫中缺摘要的文章重新補抓摘要，補完後執行 `--rescore` 更新分數。

## 摘要來源
OpenAlex 沒有摘要時依序嘗試：Crossref → 出版社文章頁面的 `<meta>` 摘要。都取不到時只用標題評分。
Elsevier 期刊（DOI 以 `10.1016/` 開頭）的頁面擋程式存取，目前沒有可用的補抓來源。

## 執行出問題時
- 部分失敗（某期刊抓取失敗、Claude 精選失敗、寄信以外的錯誤）：信件最上方列出問題，主旨加註「執行有問題」；
  即使沒有入選文章、`send_empty` 為 false 也會寄出。
- 整個流程中斷：另寄一封「執行失敗」通知給收件人。
- 設定錯誤或 SMTP 本身失效時無法寄信，只能從 `data/logs/` 的記錄檔或 `docker compose logs app` 得知。

## 查詢紀錄（SQLite）
資料庫在 `data/journal.db`（掛載到容器的 `/app/data`）。

- `runs`：每次執行的時間、回溯區間、各期刊抓取數、新文章數、入選數、寄送狀態、錯誤、Claude 精選
- `articles`：所有看過的文章（DOI 為主鍵，用來去重），含主題、分數（`scores` 為各主題分數）、是否入選

```bash
sqlite3 data/journal.db "SELECT run_at, new_count, selected, mail_status FROM runs ORDER BY id DESC LIMIT 5"
sqlite3 data/journal.db "SELECT score, topic, title FROM articles WHERE selected ORDER BY first_seen DESC LIMIT 20"
```

## 開發
```bash
uv run pytest
```
