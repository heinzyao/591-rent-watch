import base64
import hashlib
import hmac

import pytest

from notify import MAX_CHARS, format_new_listings, verify_signature
from rent591 import Listing


def make(listing_id: str, metro: str | None = "距雙連 501公尺") -> Listing:
    return Listing(
        id=listing_id, title="測試物件", price="25,000", size="7坪",
        kind="獨立套房", floor="3F/9F", address="中山區-林森北路",
        metro=metro, url=f"https://rent.591.com.tw/{listing_id}",
    )


# ---- 簽章 ----

def test_verify_signature_accepts_valid(monkeypatch):
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "topsecret")
    body = b'{"events":[]}'
    digest = hmac.new(b"topsecret", body, hashlib.sha256).digest()
    assert verify_signature(body, base64.b64encode(digest).decode()) is True


def test_verify_signature_rejects_tampered_body(monkeypatch):
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "topsecret")
    digest = hmac.new(b"topsecret", b'{"events":[]}', hashlib.sha256).digest()
    assert verify_signature(b'{"events":["evil"]}', base64.b64encode(digest).decode()) is False


def test_verify_signature_rejects_missing_header(monkeypatch):
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "topsecret")
    assert verify_signature(b"{}", None) is False


def test_verify_signature_rejects_garbage(monkeypatch):
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "topsecret")
    assert verify_signature(b"{}", "not-base64!!") is False


def test_verify_signature_rejects_non_ascii_header(monkeypatch):
    # hmac.compare_digest 對非 ASCII 的 str 會拋 TypeError，
    # 而這個 header 來自公開端點，任何人都能送
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "topsecret")
    assert verify_signature(b"{}", "café") is False


# ---- 訊息格式化 ----

def test_format_includes_total_count_and_group_name():
    messages = format_new_listings([("中山區套房", [make("1"), make("2")])])
    assert len(messages) == 1
    assert "新物件 2 筆" in messages[0]
    assert "▍中山區套房" in messages[0]


def test_format_includes_listing_details_and_url():
    messages = format_new_listings([("中山區套房", [make("21901752")])])
    text = messages[0]
    assert "25,000 元/月" in text
    assert "7坪" in text
    assert "獨立套房" in text
    assert "中山區-林森北路" in text
    assert "https://rent.591.com.tw/21901752" in text


def test_format_includes_title_and_floor():
    messages = format_new_listings([("測試", [make("1")])])
    assert "測試物件" in messages[0]
    assert "3F/9F" in messages[0]


def test_format_omits_metro_line_when_absent():
    messages = format_new_listings([("測試", [make("1", metro=None)])])
    assert "距" not in messages[0]


def test_format_skips_groups_with_no_new_listings():
    messages = format_new_listings([("有貨", [make("1")]), ("沒貨", [])])
    assert "沒貨" not in messages[0]
    assert "有貨" in messages[0]


def test_format_returns_empty_when_nothing_new():
    assert format_new_listings([("甲", []), ("乙", [])]) == []


def test_format_splits_long_output_into_multiple_messages():
    groups = [("大量", [make(str(i)) for i in range(200)])]
    messages = format_new_listings(groups)
    assert len(messages) > 1
    for text in messages:
        assert len(text) <= MAX_CHARS


def test_format_never_splits_mid_listing():
    groups = [("大量", [make(str(i)) for i in range(200)])]
    for text in format_new_listings(groups):
        # 每筆物件都以網址結尾，網址數量應等於完整區塊數量
        assert text.count("https://rent.591.com.tw/") == text.count("元/月")
