"""LINE Messaging API：簽章驗證、訊息格式化與推播。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

import requests

from rent591 import Listing

API_BASE = "https://api.line.me/v2/bot/message"
# LINE 單則訊息上限 5000 字元，留一點餘裕
MAX_CHARS = 4800


def verify_signature(body: bytes, signature: str | None) -> bool:
    """驗證 X-Line-Signature。webhook 是公開端點，這是唯一的來源驗證。"""
    if not signature:
        return False
    secret = os.environ["LINE_CHANNEL_SECRET"].encode()
    expected = base64.b64encode(hmac.new(secret, body, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(expected.encode(), signature.encode("utf-8", "replace"))


def _format_listing(listing: Listing) -> str:
    lines = [
        listing.title[:40],
        f"{listing.price} 元/月｜{listing.size}｜{listing.kind}｜{listing.floor}",
        listing.address if listing.metro is None else f"{listing.address}｜{listing.metro}",
        listing.url,
    ]
    return "\n".join(lines)


def format_new_listings(groups: list[tuple[str, list[Listing]]]) -> list[str]:
    """把各組訂閱的新物件格式化成一或多則訊息。

    groups 是 (訂閱名稱, 新物件清單)。全部為空時回空清單，呼叫端據此不發訊息。
    超過 MAX_CHARS 時切成多則，且絕不從單筆物件中間切開。
    """
    non_empty = [(name, items) for name, items in groups if items]
    if not non_empty:
        return []

    total = sum(len(items) for _, items in non_empty)
    blocks = [f"🏠 今日新物件 {total} 筆"]
    for name, items in non_empty:
        blocks.append(f"▍{name}")
        blocks.extend(_format_listing(item) for item in items)

    messages: list[str] = []
    current: list[str] = []
    length = 0
    for block in blocks:
        # +2 是區塊之間的空行
        if current and length + len(block) + 2 > MAX_CHARS:
            messages.append("\n\n".join(current))
            current, length = [], 0
        current.append(block)
        length += len(block) + 2
    if current:
        messages.append("\n\n".join(current))

    return messages


def _post(path: str, payload: dict) -> None:
    response = requests.post(
        f"{API_BASE}/{path}",
        headers={
            "Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15,
    )
    response.raise_for_status()


def reply(reply_token: str, text: str) -> None:
    """回應對話。不計入推播額度，且不需要知道 userId。"""
    _post("reply", {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]})


def broadcast(text: str) -> None:
    """推播給所有好友。只有本人是好友，所以等同推給自己，省掉取得 userId 的流程。"""
    _post("broadcast", {"messages": [{"type": "text", "text": text}]})


def broadcast_all(texts: list[str]) -> None:
    """依序推播多則。任一則失敗就往外拋，由呼叫端決定不更新 seen。"""
    for text in texts:
        broadcast(text)
