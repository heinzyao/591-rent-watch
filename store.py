"""訂閱清單的持久化：GCS 上的單一 JSON blob。

只需要「一個清單」，用不到文件資料庫的任何能力，所以不用 Firestore。
"""

from __future__ import annotations

import json
import os

from google.cloud import storage

BLOB_PATH = "591-rent-watch/subs.json"
SEEN_LIMIT = 1000

_client: storage.Client | None = None


def _blob():
    global _client
    if _client is None:
        _client = storage.Client()
    return _client.bucket(os.environ["GCS_BUCKET"]).blob(BLOB_PATH)


def trim_seen(seen: list[str]) -> list[str]:
    """只保留最近 SEEN_LIMIT 筆 id，避免檔案無限膨脹。新 id 在尾端。"""
    return seen[-SEEN_LIMIT:]


def load_subs() -> dict:
    """讀取訂閱清單。blob 不存在（第一次執行）時回空清單。"""
    blob = _blob()
    if not blob.exists():
        return {"subs": []}
    return json.loads(blob.download_as_text())


def save_subs(data: dict) -> None:
    """整份覆寫回 GCS。

    # ponytail: 無鎖。單人使用，webhook 與 cron 同時寫入的機率可忽略；
    # 若真的撞到，改用 blob.upload_from_string(..., if_generation_match=gen) 樂觀鎖。
    """
    for sub in data["subs"]:
        sub["seen"] = trim_seen(sub["seen"])
    _blob().upload_from_string(
        json.dumps(data, ensure_ascii=False), content_type="application/json"
    )
