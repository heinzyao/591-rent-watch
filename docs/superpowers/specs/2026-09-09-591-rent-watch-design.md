# 591 租屋自動監控與 LINE 通知 — 設計文件

日期：2026-09-09
狀態：待實作

## 目標

每天定時依指定搜尋條件抓取 591 租屋網，將**新上架**的物件資訊與連結透過 LINE 推播到手機。

## 資料來源決策

實測結論（2026-09-09 驗證）：

- `https://rent.591.com.tw/list?<query>` 是 **SSR 頁面**，HTML 內已含完整物件資料，每頁 30 筆
- 每筆物件是一個 `<div class="item" data-id="{houseId}">`，內含標題、租金、坪數、房型、樓層、行政區、路名、捷運距離、出租者、更新時間、連結
- `sort=posttime_desc` 可強制「最新上架」排序（已驗證 id 遞減）
- `page=N` 分頁正常運作
- 純 `GET` + 一般 User-Agent 即可，**不需要 cookie、CSRF token 或登入**

因此採用 `requests` 抓 HTML + 解析，不使用 Playwright，也不逆向 `bff-house.591.com.tw` API。

被否決的方案：

| 方案 | 否決理由 |
|---|---|
| Playwright | Cloud Run image 需塞 Chromium，體積與記憶體成本高，本案不需要執行 JS |
| 逆向 BFF API | 路徑不在公開 bundle 中，需 device header／token，維護成本最高且易被封 |

## 搜尋條件設定方式

使用者在 591 網站上把條件（地區／租金／坪數／房型／捷運等）調到滿意，**直接複製網址**貼進 `config.toml`。

程式對這個網址只做兩件事：
1. 覆寫（或補上）`sort=posttime_desc`，確保最新物件在第一頁
2. 逐頁附加 `page=1..N`

不維護任何縣市／鄉鎮代碼對照表 —— 591 自己的網址就是最完整的參數表達方式。

## 專案結構

```
591-rent-watch/
├── main.py                    # fetch → parse → diff → notify
├── config.toml                # 搜尋網址、頁數
├── Dockerfile
├── pyproject.toml
├── docs/sample-list.html      # 真實 HTML fixture（已保存）
└── tests/test_parse.py
```

單一 `main.py`。不切 package、不做 service layer、不建 ORM。

## 元件與介面

```python
@dataclass
class Listing:
    id: str
    title: str
    price: str        # "25,000 元/月"
    size: str         # "7坪"
    kind: str         # "獨立套房"
    address: str      # "中山區-林森北路"
    metro: str | None # "距雙連 501公尺"
    url: str

fetch(search_url: str, pages: int) -> list[str]
    # 純 I/O。回傳每頁的 HTML 字串。

parse(html: str) -> list[Listing]
    # 純函式。切 div.item[data-id] 並抽欄位。
    # 唯一會因 591 改版而損壞的元件，故隔離並以 fixture 測試。

diff(listings: list[Listing], seen: set[str]) -> list[Listing]
    # 純函式。回傳 id 不在 seen 中的物件。

load_seen() -> set[str]  /  save_seen(ids: set[str]) -> None
    # GCS 單一 blob seen.json 的讀寫。

notify(listings: list[Listing]) -> None
    # LINE Messaging API broadcast。

main() -> int
    # 串接上述，回傳 exit code。
```

`fetch`／`notify`／`load_seen`／`save_seen` 是 I/O 邊界，`parse`／`diff` 是純函式可獨立測試。

## 資料流

1. 讀 `config.toml` 取得 `search_url` 與 `pages`（預設 3，即 90 筆）
2. `fetch` 抓取 N 頁 HTML
3. `parse` 各頁並合併，依 id 去重
4. `load_seen` 從 GCS 讀取已看過的 id 集合
5. `diff` 得出新物件；**若無新物件則靜默結束**（不發訊息、不寫狀態）
6. `notify` 發送 LINE broadcast
7. 推播成功後才 `save_seen`

## LINE 通知

- 新開一個專屬 Messaging API channel，**只做推播、不設 webhook**
- 使用 **broadcast** 而非 push-to-userId：只有本人加該 channel 好友，broadcast 即等同推給自己，因此**不需要取得 userId**，省掉一整套 webhook 取得 userId 的流程
- 純文字訊息，格式：

```
🏠 今日新物件 3 筆

25,000 元/月｜7坪｜獨立套房
中山區-林森北路｜距雙連 501m
https://rent.591.com.tw/21901752

24,800 元/月｜10坪｜分租套房
大安區-大安路一段｜距忠孝復興 235m
https://rent.591.com.tw/21822928
```

- LINE 單則訊息上限 5000 字元，超過時自動切成多則發送

## 錯誤處理

以下三點是刻意保留的複雜度，不得簡化：

1. **解析結果為 0 筆 → 視為失敗**。不更新 `seen.json`、發送告警訊息、`exit 1`。
   若不擋這條，591 改版當天狀態會被清空，隔天會推播出整批重複物件。
2. **LINE 推播失敗 → 不更新 `seen.json`**，讓下次執行重推，避免漏掉物件。
3. **`seen.json` 只保留最近 1000 筆 id**，避免檔案無限膨脹。

`fetch` 對單頁失敗採重試一次；若第一頁就失敗則整體失敗，後續頁失敗則以已取得的頁數繼續。

## 狀態儲存

GCS 單一 blob：`gs://<bucket>/591-rent-watch/seen.json`，內容為 `{"ids": ["21901752", ...]}`。

一次讀、一次寫，無 schema、無 index、無查詢需求。不使用 Firestore —— 本案只需要「一堆 id」，用不到文件資料庫的任何能力。

## 部署

- **Cloud Run Job**（非 Service，本程式無需常駐監聽）
- **Cloud Scheduler** 每天 09:00 (Asia/Taipei) 觸發
- **Secret Manager** 存放 `LINE_CHANNEL_ACCESS_TOKEN`（沿用專屬 secret 命名慣例，如 `RENT591_LINE_CHANNEL_ACCESS_TOKEN`）
- 流程與既有 `distiller` / `cat-lendar` 專案一致

## 測試

`tests/test_parse.py`，以 `docs/sample-list.html` 為 fixture：

- `parse` 對 fixture 回傳 30 筆
- 首筆各欄位值正確（id、租金、坪數、房型、地址、url）
- 每筆的 `url` 皆符合 `https://rent.591.com.tw/<數字>`
- `diff` 在給定 seen 集合時正確排除已看過的 id

執行：`uv run python -m pytest tests/ -q`

不寫 `fetch`／`notify` 的測試 —— 那是薄薄的 I/O 包裝，mock 掉之後測到的只是 mock 本身。

## 明確不做（YAGNI）

- 不做降價追蹤（目前只要新物件；要加時在 `seen.json` 多存 price 欄位即可）
- 不做互動式 LINE 指令設定條件（改條件就改 `config.toml` 重新部署）
- 不做多組搜尋條件（需要時 `config.toml` 改成清單，迴圈跑）
- 不存物件歷史、不做網頁介面、不做資料庫
