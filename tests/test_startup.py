"""驗證缺少環境變數時，程式會拒絕啟動。

這個檢查必須用 subprocess 驗證：conftest.py 在測試程序裡已經填好了環境變數，
in-process 匯入 main 永遠不會觸發檢查。
"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
REQUIRED = ("GCS_BUCKET", "CRON_KEY", "LINE_CHANNEL_SECRET", "LINE_CHANNEL_ACCESS_TOKEN")


def _run_import_without(*missing: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in missing}
    for name in REQUIRED:
        if name not in missing:
            env[name] = "dummy"
    return subprocess.run(
        [sys.executable, "-c", "import main"],
        env=env,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )


def test_missing_env_var_refuses_to_start():
    result = _run_import_without("GCS_BUCKET")
    assert result.returncode != 0
    assert "缺少必要環境變數" in result.stderr
    assert "GCS_BUCKET" in result.stderr


def test_all_env_vars_present_imports_fine():
    result = _run_import_without()
    assert result.returncode == 0, result.stderr
