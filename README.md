# journal-featured 期刊選讀

每週從指定期刊抓新文章（OpenAlex），以 embedding 語意相似度比對感興趣主題，
查詢紀錄存入 SQLite（`data/journal.db`），入選文章以 Email 寄出。

## 設定
1. `config.yaml`：先 `cp config.example.yaml config.yaml`（此檔含收件人等個人設定，不進 git；一定要在 `docker compose up` 前建立，否則 Docker 會把它建成資料夾）；期刊（名稱 + ISSN）、主題（名稱 + 一段描述）、門檻、收件人、排程 `schedule`、`db_path`
   - 查 ISSN：`uv run journal-featured --lookup "期刊名稱"`
2. `data/secrets.env`：API 金鑰與寄信設定，啟動後到網頁「API 與寄信」頁填寫即可（也可手動建立）：`OPENALEX_API_KEY`、`ANTHROPIC_API_KEY`（選填，Claude 精選）、`SMTP_*`（Gmail 帳號 + [應用程式密碼](https://myaccount.google.com/apppasswords)）
3. `.env`（選填）：只用來覆蓋部署變數 `JOURNAL_WEB_BIND`、`TZ`，見 `.env.example`

設定位置只有一條規則：**金鑰在 `data/secrets.env`，其餘都在 `config.yaml`**，兩者都能在網頁上修改。

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

## 網頁介面
`docker compose up -d` 會同時啟動 `web` 服務，開啟 http://127.0.0.1:8501 ：

- **本週選讀**：各期 Claude 精選與依主題分組的入選文章，含簡評、摘要、信件預覽與下次排程時間；☆ 可加入收藏
- **文章庫**：所有看過的文章，依關鍵字、範圍（入選／收藏／全部）、期刊、主題、日期、分數篩選，匯出 CSV / BibTeX
- **執行紀錄**：每次執行的結果與錯誤、各期刊抓取數；連續抓到 0 篇的期刊會標警告
- **手動執行**：正式執行、試跑，及執行不寄信、重新精選、重寄（寄信前會跳出確認）；排程與手動執行的輸出都存於 `data/logs/` 並可在此頁查看
- **主題與期刊**：分頁編輯主題、期刊、排程與收件人、Claude 精選、進階（embedding 模型、還原備份），各分頁分別儲存；
  寫回 `config.yaml` 時保留註解，舊版備份到 `data/config-backups/`；查詢 ISSN 後可直接加入期刊
- **門檻校準**：各主題的分數分布直方圖、收藏文章位置、門檻附近的文章；試調門檻可即時看入選數變化，確認後一鍵套用
- **API 與寄信**：填寫 OpenAlex、Anthropic 金鑰與 SMTP，可測試連線、寄測試信

說明：
- `web` 與 `app` 共用同一映像檔；`app` 只負責排程，`config.yaml` 仍唯讀掛載，只有 `web` 能寫
- 排程與網頁觸發的執行以 `data/run.lock` 互斥，同時只會有一個在跑（另一個會以代碼 3 略過）
- 預設只綁定本機；要從其他電腦連線可在 `.env` 設 `JOURNAL_WEB_BIND=0.0.0.0`（介面沒有登入機制，請只在可信任的網路使用）
- 直接在主機上編輯 `config.yaml` 時，請用會就地寫入的編輯器；若編輯器以新檔取代原檔，容器內仍會看到舊版，需 `docker compose restart`

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

`--rescore`：以目前的主題描述與模型重新計算資料庫中所有文章的各主題分數（門檻校準頁用），不改變各期的入選紀錄；
網頁「門檻校準」頁也有按鈕可執行。

## 查詢紀錄（SQLite）
資料庫在 `data/journal.db`（掛載到容器的 `/app/data`）。

- `runs`：每次執行的時間、回溯區間、各期刊抓取數、新文章數、入選數、寄送狀態、錯誤、Claude 精選
- `articles`：所有看過的文章（DOI 為主鍵，用來去重），含主題、分數（`scores` 為各主題分數）、是否入選
- `stars`：網頁上收藏的文章（DOI、收藏時間）

```bash
sqlite3 data/journal.db "SELECT run_at, new_count, selected, mail_status FROM runs ORDER BY id DESC LIMIT 5"
sqlite3 data/journal.db "SELECT score, topic, title FROM articles WHERE selected ORDER BY first_seen DESC LIMIT 20"
```

## 開發
```bash
uv run pytest
```
