# 實作紀錄

這份文件記錄本專案從計畫到合併的完整執行過程：每個任務的審查結論、被推翻的判斷，
以及那些測試不會告訴你的問題是怎麼被發現的。

保留它的理由：程式碼只有 447 行，但過程中攔下的幾個問題都不是靠讀程式碼或跑測試
找到的 —— 591 憑證鏈缺 Subject Key Identifier 導致服務完全抓不到、抓取失敗的通知
在最需要它的時候靜默消失、以及修正一個缺陷時在另一處複製出的同型迴歸。下次改動這個
專案時，這份紀錄比 git log 更能說明「為什麼是這樣寫」。

相關文件：

- 設計：[`specs/2026-09-09-591-rent-watch-design.md`](specs/2026-09-09-591-rent-watch-design.md)
- 實作計畫：[`plans/2026-09-10-591-rent-watch.md`](plans/2026-09-10-591-rent-watch.md)

實作在分支 `feat/implementation` 上進行（merge base `2c780bf`），完成後已合併回 main 並刪除。

---

Task 1: complete (commits c16e66f..5d23cf7, review clean)
  - spec ✅ / quality Approved
  - Important 已修：parse 對缺 href 的物件改為跳過而非 KeyError（+1 測試）
  - Minor 已順帶修：_txt 補上 Tag | None 型別標註
  - ⚠️ 已由 controller 解決：:has() 來自 soupsieve 2.9.2（已鎖 uv.lock），實測正常
  - 測試：6 passed
Task 2: complete (commits 4ea0f7b..af26796, review pending)
  - 實作者回報 DONE_WITH_CONCERNS：無法連上 591
  - controller 診斷出封鎖性問題：591 憑證鏈缺 SKI，OpenSSL 3.5+ VERIFY_X509_STRICT 拒絕
  - 已在部署映像 python:3.13-slim 重現並修復，非本機環境問題
  - 修正保留完整憑證驗證，僅放寬格式嚴格性檢查（+1 測試鎖住此不變條件）
  - 測試：16 passed；實測本機 60 筆、部署映像 30 筆
  - spec 已補「TLS 相容性」章節
Task 3: complete (commit 54d8dd7 + fix pending, review 有 Important)
  - spec ✅ / quality Changes Requested
  - Important：SEARCH_URL_RE 用 \S+ 會把全形標點與後續中文吞進網址（中文輸入常態），
    導致監控條件靜默損毀。controller 驗證修法後派 fixer 處理中
  - 陷阱：半形逗號是 591 的 section=5,7 合法用法，不可從字元集排除
Task 4: complete (commit 316edf0, controller 驗證 34 passed，無多餘 mock 測試)
Task 5: complete (commit 50c596f, 45 passed)
  - DONE_WITH_CONCERNS：計畫寫 12 個測試，brief 實際只有 11 個（我計畫階段數錯）
  - implementer 誠實回報且未偷加測試湊數，行為正確
Task 2 fix: 3e1d2eb — 補 fetch 4 個分支測試 + session adapter 測試 + /list 路徑檢查，51 passed
Task 3 fix: a0da5e8 — 網址正則改用可見 ASCII 集 + 剝除句尾標點，56 passed
Task 6: complete (commit caf595f, 69 passed)
  - DONE_WITH_CONCERNS：計畫的測試斷言（"無法"/"失敗"）與實作訊息（"這不像是..."）互相矛盾
  - implementer 改訊息為「無法辨識這個網址，請從 rent.591.com.tw 的搜尋結果頁複製。」
  - controller 裁決：接受。保留了指引性，訊息品質未下降，斷言變得有意義
  - 已驗證：ponytail 註解有加、fetch 為模組層級呼叫（monkeypatch 攔得到）
Task 7: complete (commit 7a514ff, 80 passed)
  - controller 獨立驗證四條不變條件全部成立：
    (1) 單組 0 筆 → failed=False（合法結果，非失敗）
    (2) 全部 0 筆 → failed=True 且 seen 完全未被動
    (3) 推播失敗 → HTTP 500 且 save_subs 呼叫 0 次
    (4) /cron 錯誤金鑰與無金鑰皆回 403
Task 6 review: spec ✅ / quality Approved，待修項目（全在 main.py，與 Task 7 findings 合併處理）：
  - Important: webhook 迴圈 try/except 只包 reply()，未包 handle_command()。
    後者拋例外會中斷整批事件並回 500，導致 LINE 重送 —— 與程式碼註解宣稱的保證不符
  - Minor: PAGE_CAP 用字面 30，應改用 rent591.PAGE_SIZE，否則 591 改版時閾值悄悄失準
  - Minor: handle_command 的 except Exception 兜底缺 # ponytail: 註解
  - Minor: 一般 Exception 分支（非 InvalidSearchURL）無測試覆蓋
  - reviewer 已確認：monkeypatch 替換真實生效，非假通過
  - reviewer 已確認：handle_command 各分支 (text, changed) 語意全部正確，
    失敗分支不回報已改動（不會把壞狀態寫回）
Task 8: complete (commit fcab6ae, 80 passed)
  - docker build 成功，映像 280MB
  - controller 額外驗證：容器實際啟動並回應請求
    GET / → 200 ✓
    POST /cron 無金鑰 → 500（期望 403）✗
    POST /webhook 偽造簽章 → 500（期望 400）✗
  - 根因：os.environ["CRON_KEY"] / ["LINE_CHANNEL_SECRET"] 缺失時 KeyError。
    測試用 monkeypatch.setenv 設好環境變數所以全綠，真實環境 secret 未注入時
    每個請求都 500，LINE 會持續重送 webhook。
  - 待修（與 Task 6/7 findings 合併）：啟動時檢查必要環境變數，fail fast
Task 7 review: spec ✅ / quality Changes Requested
  - CRITICAL: run_daily 的 errors 只在 messages 非空時才附加，導致
    (a) 全部訂閱都拋例外時 fetched_counts 為空 list → 改版判定不觸發 → 回 200 且靜默寫回
    (b) 一組失敗但其他組今天沒新物件時（常態）→ 失敗通知消失
    使用者完全收不到訊息，與「今天沒新物件」無法區分。已派 fixer。
  - Minor: run_daily 判定失敗前已就地改 last_count（目前無害，靠呼叫端紀律，補測試鎖住）
  - Minor: 單一訂閱 false positive 的既有註解未用 # ponytail: 格式

Controller 裁決：容器實測的「secret 未注入 → 500 而非 403/400」不修。
  理由：改回 400 會讓 LINE 不再重送，但也讓配置錯誤變得難以察覺；
  現況的 500 + KeyError traceback 會在 Cloud Run log 直接指名缺哪個環境變數，
  對運維反而更明顯。deploy.sh 已用 --set-secrets 正確注入。
  已列入終審 triage 讓 reviewer 有機會反駁此判斷。
Fix wave: 763cfc4 — 84 passed
  - CRITICAL 已修並經 controller 獨立驗證三情境：
    A) 全部訂閱失敗 → 現在會發「⚠️ 以下條件本次抓取失敗…甲、乙」（修復前靜默）
    B) 一組失敗+其他組無新物件 → 現在會發通知（修復前靜默）
    C) webhook 事件處理拋例外 → 回 200（修復前 500，會導致 LINE 重送整批）
  - Important + 5 Minor 一併處理完畢
所有 8 個 task 完成。進入終審。

## 終審（opus, 整支分支）
判定：修完 3 項再合併。無 Critical。
- controller 的「secret 缺失不修」裁決被推翻，理由成立：
  問題不在狀態碼而在偵測時機。GET / 不碰環境變數 → 健康檢查必過 → 壞 revision 上全量流量；
  /cron 偵測延遲最長 24h 且無 alerting；GCS_BUCKET 無 Secret Manager 後盾（controller 完全漏掉）。
  已改為啟動時檢查，revision 不 ready 就不切流量。
- I1: 非 ASCII 的 X-Line-Signature → hmac.compare_digest 拋 TypeError → 公開端點 500。已修為 bytes 比對。
- I2: /cron 序列跑完所有訂閱，3 組即超過 Cloud Run 300s 預設逾時。timeout 20s→8s + deploy.sh --timeout 600。
      並修正 Dockerfile 錯誤註解（--timeout 對 gthread worker 不限制單請求長度）。
- I3: deploy.sh 漏 IAM 授權，第一次部署會在第一個請求 500。已補。
- M1/M2 測試洞：save_subs 只有負向斷言、簽章接線無端到端測試。已補。
- M3/M5/M6/M7 一併處理。M4/M9/M10 列 backlog。
- 終審確認無誤：狀態機無「記錄了但沒推播」窗口；SSRF 七種繞過皆被擋；無過度設計。

fix wave: c173420 + 測試衝突裁決
  - fixer 正確回報既有測試與新行為衝突而未擅改，controller 裁決改測試（其意圖是驗自動編號，非重複網址）
  - 最終 91 passed

最終容器驗收：
  GET / → 200 | /cron 無金鑰 → 403 | /cron 錯金鑰 → 403
  /webhook 偽造簽章 → 400 | /webhook 非ASCII簽章 → 400
  缺環境變數 → RuntimeError 拒絕啟動
  （修正前為 200 / 500 / 500 / 500 / 500 / 正常啟動）

狀態：8 個 task 全部完成並通過終審必修項。待人工驗證後即可合併。

## 複審（opus, 修正後）
判定：還要修 1 項 Critical。
- C1 (迴歸)：上一波把 /cron 金鑰比對改成 compare_digest 時，引入與 notify.py
  同型的缺陷 —— 非 ASCII 的 X-Cron-Key 拋 TypeError → 公開端點 500。
  controller 的容器實測沒抓到，因為只驗了 /webhook 的非 ASCII，/cron 只驗 ASCII 錯金鑰。
- I1：deploy.sh 的 IAM 授權在 gcloud run deploy 之後，但 --set-secrets 在 instance
  啟動時解析，沒權限則 revision 起不來 → set -e 中止 → 授權永遠執行不到。已移到部署前。
- M1：突變測試證實啟動檢查刪掉後 91 passed 全綠（零覆蓋）。已補 subprocess 測試。
- 複審確認 controller 的測試裁決正確（非遷就實作），seen 狀態機不變條件仍成立。
- 複審修正 controller 認知：timeout=8 是單次 socket read 上限，非總時長硬保證。

fix: 53321ad — 95 passed
controller 獨立驗收：
  兩處 compare_digest 皆為 bytes 比對；deploy.sh 授權確在 deploy 之前
  突變測試：拿掉啟動檢查 → test_startup 確實 FAIL（守得住）
  容器八項（含額外的 emoji 邊界）：200/403/403/403/403/400/400/400

## 第三輪複審（opus, 最終確認）
判定：**可以合併**。無 Critical、無 Important。4 項 Minor 已全數修畢。
- 複審用 mutation testing 揭穿兩個測試假象（還原修正後 95 passed 全綠）：
  失敗附註「獨立一則」零覆蓋、上限 10 組只覆蓋上邊界
- Minor 4（本批引入）：deploy.sh 推導預設 SA 卻未在 gcloud run deploy 釘住，
  service 若曾綁自訂 SA 則授權打到錯 principal 且靜默。已加 --service-account "$SA"
- 前置清單漏 compute.googleapis.com（預設 compute SA 需它才建立），已補
- spec 兩處描述失敗通知只改一處造成自相矛盾，已同步
- 複審確認：/cron 與 notify 的 bytes 比對真正等價、無可觸發例外或誤判相等
- 複審主動掃同型破口：webhook 迴圈另有一處畸形輸入路徑，但被簽章驗證擋在前面，
  明確建議不在合併前處理

fix: cd40432 — 96 passed
controller 最終驗收：96 passed | deploy.sh 兩處修正到位且語法通過 |
  spec 無舊說法殘留 | 工作樹乾淨

## 結論
三輪審查、五波修正完成。可以合併。
