"""測試用的環境變數預設值。

main.py 在 import 時就會檢查必要環境變數，這裡先填上假值讓測試能載入模組。
個別測試若要驗證特定值，仍可用 monkeypatch.setenv 覆寫。
"""

import os

os.environ.setdefault("GCS_BUCKET", "test-bucket")
os.environ.setdefault("CRON_KEY", "test-cron-key")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test-secret")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test-token")
