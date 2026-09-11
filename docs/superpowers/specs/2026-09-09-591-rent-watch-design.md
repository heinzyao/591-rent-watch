# 591 租屋自動監控與 LINE 通知 — 設計文件

日期：2026-09-09（2026-09-10 修訂：設定改由 LINE 對話進行，支援多組搜尋條件）
狀態：待實作

## 目標

依多組使用者自訂的搜尋條件，每天定時抓取 591 租屋網，將**新上架**的物件資訊與連結透過 LINE 推播到手機。搜尋條件完全在 LINE 對話中管理，貼上 591 網址即可新增。

## 資料來源決策

實測結論（2026-09-09 / 09-10 驗證）：

- `https://rent.591.com.tw/list?<query>` 是 **SSR 頁面**，HTML 內已含完整物件資料，每頁 30 筆
- 每筆物件是一個 `<div class="item" data-id="{houseId}">`，內含標題、租金、坪數、房型、樓層、行政區、路名、捷運距離、出租者、更新時間、連結
- `sort=posttime_desc` 可強制「最新上架」排序（已驗證 id 遞減）
- `page=N` 分頁正常；超出範圍的頁數回傳 0 筆
- **0 筆是合法結果**（條件過嚴或頁數超界），不可逕自視為解析失敗
- 純 `GET` + 一般 User-Agent 即可，**不需要 cookie、CSRF token 或登入**
- HTML 中**沒有**「符合共 N 筆」的總數欄位，總數由實際解析筆數推得

因此採用 `requests` 抓 HTML + `BeautifulSoup` 解析，不使用 Playwright，也不逆向 `bff-house.591.com.tw` API。

被否決的方案：

| 方案 | 否決理由 |
|---|---|
| Playwright | Cloud Run image 需塞 Chromium，體積與記憶體成本高，本案不需要執行 JS |
| 逆向 BFF API | 路徑不在公開 bundle 中，需 device header／token，維護成本最高且易被封 |

## 搜尋條件管理（LINE 對話）

使用者在 591 網站上把條件（地區／租金／坪數／房型／捷運等）調到滿意，**複製網址貼進 LINE 對話**。

不維護任何縣市／鄉鎮代碼對照表 —— 591 自己的網址就是最完整的參數表達方式。

### 指令解析規則

`parse_command(text) -> Command` 是純函式，依序判斷：

| 輸入 | 動作 |
|---|---|
| 訊息中含 `rent.591.com.tw/list` 網址 | 新增訂閱。網址以外的文字 strip 後作為名稱；若無文字則命名為「條件 N」 |
| `清單` 或 `list` | 列出所有訂閱，含編號與上次抓取筆數 |
| `刪除 N` 或 `del N` | 刪除第 N 組訂閱 |
| 其他 | 回覆簡短使用說明 |

只有三種操作，因此不使用 slash 指令語法、不做狀態機、不接 LLM 做語意分析。

### 對話範例

```
你：中山區套房 https://rent.591.com.tw/list?region=1&section=5&...
它：✅ 已新增「中山區套房」
    目前符合 47 筆，已記錄為基準，明天起只推新上架的物件。

你：清單
它：目前 2 組條件
    1. 中山區套房（47 筆）
    2. 大安區電梯（12 筆）

你：刪除 2
它：🗑 已刪除「大安區電梯」
```

### 新增時的即時驗證

新增訂閱時立即抓取一次，用途有三：

1. 驗證網址有效、能正常解析
2. 回報目前符合筆數，讓使用者當場知道條件是否太寬或太嚴
3. 把現有物件全數寫入該組的 `seen`，避免隔天湧出一整批「新物件」

若抓到 **0 筆**，仍然新增，但回覆提醒「目前 0 筆，條件可能過嚴或網址有誤」。
若抓滿 `pages × 30` 筆（預設 90），回覆提醒「條件較寬，建議收緊」。

## TLS 相容性（實作階段發現）

591 的憑證鏈不符 RFC 5280 嚴格要求：中間憑證 `TWCA Secure SSL Certification Authority`
缺少 Subject Key Identifier。Python 3.13+ 搭配 OpenSSL 3.5+ 預設啟用 `ssl.VERIFY_X509_STRICT`，
會直接拒絕連線（`CERTIFICATE_VERIFY_FAILED: Missing Subject Key Identifier`）。
已在部署目標映像 `python:3.13-slim`（OpenSSL 3.5.7）中確認，非本機環境問題。

`rent591._ssl_context()` 只清除 `VERIFY_X509_STRICT` 這一項格式檢查，
信任鏈、主機名與有效期驗證全部保留 —— 與 `verify=False` 有本質差異。
測試 `test_ssl_context_keeps_verification_but_drops_strict_format_check` 鎖住這個不變條件。

## 相依套件

`flask`、`gunicorn`、`requests`、`beautifulsoup4`、`lxml`、`google-cloud-storage`。
皆為 `distiller` 已在使用的套件。不新增任何依賴。

## 專案結構

```
591-rent-watch/
├── main.py                    # Flask routes + handle_command / run_daily
├── rent591.py                 # Listing / fetch / parse / diff
├── commands.py                # parse_command
├── store.py                   # GCS subs.json 讀寫
├── notify.py                  # 簽章驗證 / 訊息格式化 / LINE 推播
├── Dockerfile
├── pyproject.toml
├── scripts/deploy.sh
├── docs/sample-list.html      # 真實 HTML fixture（已保存）
└── tests/                     # test_parse / test_fetch_diff / test_command
                               # test_store / test_notify / test_webhook / test_cron
```

五個檔案，切分依據是**測試邊界**：純函式集中在 `rent591.py` / `commands.py` / `notify.py`，
I/O 隔離在 `store.py` 與 `main.py`。`rent591.py` 不 import Flask 也不 import LINE。

## 元件與介面

```python
# ---- rent591.py：與 LINE、Flask 完全無關 ----

@dataclass
class Listing:
    id: str
    title: str
    price: str        # "25,000"（「元/月」在 notify 格式化時才拼上）
    size: str         # "7坪"
    kind: str         # "獨立套房"
    floor: str        # "3F/9F"、"頂樓加蓋/4F"
    address: str      # "中山區-林森北路"
    metro: str | None # "距雙連 501公尺"，非近捷運物件為 None
    url: str

normalize_url(search_url: str, page: int) -> str
    # 驗證網域與路徑（見「安全性」）、強制 sort=posttime_desc、設定頁碼。
    # 不符時拋 InvalidSearchURL。

fetch(search_url: str, pages: int = 3) -> list[Listing]
    # I/O。逐頁抓取後直接 parse 並依 id 去重，回傳合併後的物件清單。

parse(html: str) -> list[Listing]
    # 純函式。以 BeautifulSoup(html, "lxml") 選取 div.item[data-id] 並抽欄位。
    # 唯一會因 591 改版而損壞的元件，故隔離並以 fixture 測試。

diff(listings: list[Listing], seen: set[str]) -> list[Listing]
    # 純函式。回傳 id 不在 seen 中的物件。

# ---- main.py ----

parse_command(text: str) -> Command
    # 純函式。見「指令解析規則」。

load_subs() -> dict  /  save_subs(subs: dict) -> None
    # GCS 單一 blob subs.json 的讀寫。

verify_signature(body: bytes, signature: str | None) -> bool
format_new_listings(groups: list[tuple[str, list[Listing]]]) -> list[str]
    # 純函式。(訂閱名稱, 新物件) 轉成訊息，超過 4800 字元切多則且不切開單筆物件。

reply(token: str, text: str) -> None       # LINE reply（回應對話用，免額度）
broadcast(text: str) -> None               # LINE broadcast（定時通知用）
broadcast_all(texts: list[str]) -> None    # 依序推播多則，任一則失敗即往外拋

handle_command(command: Command, subs: dict) -> tuple[str, bool]
    # 純邏輯（僅 fetch 為 I/O）。回傳 (回覆文字, subs 是否被改動)。

run_daily(subs: dict) -> tuple[list[str], bool]
    # 回傳 (要推播的訊息, 是否判定為解析失敗)。

POST /webhook   # LINE 事件進入點
POST /cron      # Cloud Scheduler 觸發
GET  /          # health check
```

`fetch` / `load_subs` / `save_subs` / `reply` / `broadcast` 是 I/O 邊界；
`parse` / `diff` / `normalize_url` / `parse_command` / `format_new_listings` /
`verify_signature` / `handle_command` / `run_daily` 是純邏輯，測試集中在這些。

## 資料模型

GCS 單一 blob：`gs://$GCS_BUCKET/591-rent-watch/subs.json`

```json
{
  "subs": [
    {
      "name": "中山區套房",
      "url": "https://rent.591.com.tw/list?region=1&section=5",
      "seen": ["21901752", "21822928"],
      "last_count": 47
    }
  ]
}
```

`seen` **每組獨立**。兩組條件重疊到同一物件時會各推一次 —— 這是正確語意（你在兩組條件下都想看到它），且省掉跨組去重的邏輯。

`seen` 每組保留最近 1000 筆 id，避免無限膨脹。

一次讀、一次寫，無 schema、無 index、無查詢需求。不使用 Firestore —— 本案只需要一個清單，用不到文件資料庫的任何能力。

## 每日執行流程（`POST /cron`）

1. `load_subs()`
2. 對每組訂閱：`fetch` → `parse` → `diff` → 收集新物件
3. **失敗判斷**：若**所有成功抓取的**訂閱都回傳 0 筆，判定為 591 改版導致解析失敗 → 發告警、不更新任何 `seen`、回 500。
   單組 0 筆屬正常（條件過嚴），照常處理。
4. 有新物件才發 LINE broadcast，依條件名稱分段。
   個別訂閱抓取失敗時另發一則獨立的失敗通知 —— 不可附加在既有訊息尾端，
   那些訊息已接近 4800 字元的切割上限。
5. **broadcast 成功後**才 `save_subs()`

訂閱組數上限 10 組：`/cron` 序列跑完所有訂閱，超過會撞上 Cloud Run 請求逾時且失敗無聲。

### 通知訊息格式

```
🏠 今日新物件 3 筆

▍中山區套房
獨立套房*全新裝潢*代收垃圾
25,000 元/月｜7坪｜獨立套房｜1F/4F
中山區-林森北路｜距雙連 501公尺
https://rent.591.com.tw/21901752

▍大安區電梯
忠孝復興／近捷運站/走路3分鐘
24,800 元/月｜10坪｜分租套房｜10F/11F
大安區-大安路一段｜距忠孝復興 235m
https://rent.591.com.tw/21822928
```

LINE 單則訊息上限 5000 字元，超過時自動切成多則發送。

## 安全性

以下為信任邊界，不簡化：

1. **LINE webhook 簽章驗證**：以 channel secret 對 request body 做 HMAC-SHA256，與 `X-Line-Signature` 比對，不符直接回 400。
2. **網址白名單**：`fetch` 只接受 host 為 `rent.591.com.tw` 的網址。使用者貼進來的網址是外部輸入，不做限制等於開放 SSRF。
3. **`/cron` 端點保護**：驗證 `X-Cron-Key` header 與 Secret Manager 中的隨機字串相符，不符回 403。
   Service 必須公開（LINE webhook 需要），故無法靠 Cloud Run IAM 保護整個服務。
   `# ponytail: 共享密鑰擋 /cron，若日後有多個排程來源改用 Cloud Scheduler OIDC + ID token 驗證`

## 錯誤處理

1. **全部訂閱皆 0 筆 → 視為解析失敗**。不更新 `subs.json`、broadcast 一則告警（「591 解析失敗，可能已改版」）、回 500 讓 Scheduler 記錄失敗。
2. **broadcast 失敗 → 不更新 `subs.json`**，讓下次執行重推，避免漏掉物件。
3. **單組 fetch 失敗** → 該組跳過且不更新其 `seen`，其他組照常處理，另發一則獨立通知說明哪組失敗。
4. `fetch` 對單頁失敗重試一次；第一頁失敗即視為該組失敗，後續頁失敗則以已取得頁數繼續。

## 部署

- **Cloud Run Service**（Flask + gunicorn），非 Job —— 需要常駐接收 LINE webhook
- **Cloud Scheduler** 每天 09:00 (Asia/Taipei) 以 `X-Cron-Key` 打 `POST /cron`
- **Secret Manager**：`RENT591_LINE_CHANNEL_SECRET`、`RENT591_LINE_CHANNEL_ACCESS_TOKEN`、`RENT591_CRON_KEY`
- **環境變數**：`GCS_BUCKET`、`PAGES`（預設 3）
- `min-instances=0`。cold start 期間 LINE 會重送 webhook，且 cron 不在意延遲。
  `# ponytail: min-instances=0，若 webhook 常逾時再調成 1`
- LINE Official Account 需關閉「自動回應訊息」，開啟 Webhook
- 流程與既有 `distiller` 專案一致

### webhook 同步處理的取捨

新增訂閱時同步抓 3 頁（約 2–3 秒）後才回覆。LINE 對 webhook 回應時間沒有硬性 1 秒限制，逾時會重送，實務上此延遲可接受。
`# ponytail: 同步抓取，若 LINE 開始重送再改成先 reply 再背景補抓`

## 測試

`tests/test_parse.py`，以 `docs/sample-list.html` 為 fixture：

- `parse` 對 fixture 回傳 30 筆
- 首筆各欄位值正確（id、租金、坪數、房型、樓層、地址、捷運、url）
- 每筆的 `url` 皆符合 `https://rent.591.com.tw/<數字>`
- `parse` 對空結果頁回傳 `[]` 而不拋例外
- `diff` 在給定 seen 集合時正確排除已看過的 id

`tests/test_command.py`：

- 貼網址 + 名稱 → 正確拆出兩者
- 貼純網址 → 名稱為「條件 N」
- `清單` / `刪除 2` / 亂打 → 對應到正確的 Command
- 非 591 網域的網址 → 被拒絕

執行：`uv run python -m pytest tests/ -q`

不寫 `fetch` / `reply` / `broadcast` / GCS 的測試 —— 那是薄薄的 I/O 包裝，mock 掉之後測到的只是 mock 本身。

## 明確不做（YAGNI）

- 不做降價追蹤（目前只要新物件；要加時在 `seen` 改存 `{id: price}` 即可）
- 不做多使用者（broadcast 推給所有好友，只有本人是好友。要多使用者時改用 push + userId，`subs.json` 加一層 user 維度）
- 不做修改既有條件（刪掉重貼即可）
- 不做 subs.json 的並發鎖（單人使用，webhook 與 cron 同時寫入的機率可忽略）
  `# ponytail: 無鎖，若真的撞到改用 GCS if_generation_match 樂觀鎖`
- 不存物件歷史、不做網頁介面、不做資料庫
