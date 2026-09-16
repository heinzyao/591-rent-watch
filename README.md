# 591 租屋監控 / 591 Rent Watch

[English](#english) | [繁體中文](#繁體中文)

---

## English

Scrapes [591.com.tw](https://rent.591.com.tw/) three times a day (09:00, 13:00, 21:00 Taipei time)
using the search filters you set, and pushes **newly listed** rentals to LINE.

### Usage

Everything happens inside the LINE chat:

| You send | Result |
|---|---|
| `中山區套房 https://rent.591.com.tw/list?region=1&...` | Add a watch with that name |
| `https://rent.591.com.tw/list?...` | Same, name is auto-numbered |
| `清單` | List all current watches |
| `刪除 2` | Delete watch #2 |

To get a search URL, set up the filters on [591](https://rent.591.com.tw/) and copy the address bar.

Adding a watch scrapes immediately and replies with the number of matches, so a bad URL shows up
right away. Those existing listings are recorded as the baseline, so the next push won't dump a
whole batch of "new" listings on you.

### Development

```bash
uv sync
uv run python -m pytest tests/ -q
```

### Deployment

```bash
PROJECT=<gcp-project> GCS_BUCKET=<bucket> ./scripts/deploy.sh
```

Architecture: Cloud Run Service (Flask) + Cloud Scheduler + GCS (stores the watch list) + Secret Manager.

### Design Docs

- Design: `docs/superpowers/specs/2026-09-09-591-rent-watch-design.md`
- Implementation plan: `docs/superpowers/plans/2026-09-10-591-rent-watch.md`
- Implementation log: `docs/superpowers/implementation-log.md` — review conclusions and the reasoning behind key decisions

---

## 繁體中文

每天 9:00、13:00、21:00（台北時間）依你設定的條件抓 591 租屋網，把**新上架**的物件推播到 LINE。

### 使用方式

全部在 LINE 對話裡完成：

| 你輸入 | 結果 |
|---|---|
| `中山區套房 https://rent.591.com.tw/list?region=1&...` | 新增監控條件 |
| `https://rent.591.com.tw/list?...` | 同上，名稱自動編號 |
| `清單` | 列出目前所有條件 |
| `刪除 2` | 刪除第 2 組條件 |

搜尋網址就到 [591 租屋網](https://rent.591.com.tw/) 把篩選條件調好，直接複製網址列。

新增時會立刻抓一次並回報符合筆數，貼錯網址當場就知道。這批現有物件會記為基準，
所以不會在下一次推播湧出一整批「新物件」。

### 開發

```bash
uv sync
uv run python -m pytest tests/ -q
```

### 部署

```bash
PROJECT=<gcp-project> GCS_BUCKET=<bucket> ./scripts/deploy.sh
```

架構：Cloud Run Service（Flask）+ Cloud Scheduler + GCS（存訂閱清單）+ Secret Manager。

### 設計文件

- 設計：`docs/superpowers/specs/2026-09-09-591-rent-watch-design.md`
- 實作計畫：`docs/superpowers/plans/2026-09-10-591-rent-watch.md`
- 實作紀錄：`docs/superpowers/implementation-log.md` — 審查結論與關鍵決策的來龍去脈
