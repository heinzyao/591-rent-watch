# 591 租屋監控

每天早上 9 點依你設定的條件抓 591 租屋網，把**新上架**的物件推播到 LINE。

## 使用方式

全部在 LINE 對話裡完成：

| 你輸入 | 結果 |
|---|---|
| `中山區套房 https://rent.591.com.tw/list?region=1&...` | 新增監控條件 |
| `https://rent.591.com.tw/list?...` | 同上，名稱自動編號 |
| `清單` | 列出目前所有條件 |
| `刪除 2` | 刪除第 2 組條件 |

搜尋網址就到 [591 租屋網](https://rent.591.com.tw/) 把篩選條件調好，直接複製網址列。

新增時會立刻抓一次並回報符合筆數，貼錯網址當場就知道。這批現有物件會記為基準，
所以不會在隔天湧出一整批「新物件」。

## 開發

```bash
uv sync
uv run python -m pytest tests/ -q
```

## 部署

```bash
PROJECT=<gcp-project> GCS_BUCKET=<bucket> ./scripts/deploy.sh
```

架構：Cloud Run Service（Flask）+ Cloud Scheduler + GCS（存訂閱清單）+ Secret Manager。

## 設計文件

- 設計：`docs/superpowers/specs/2026-09-09-591-rent-watch-design.md`
- 實作計畫：`docs/superpowers/plans/2026-09-10-591-rent-watch.md`
