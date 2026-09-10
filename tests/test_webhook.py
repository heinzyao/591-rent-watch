import pytest

from commands import AddSub, DeleteSub, Help, ListSubs
from rent591 import InvalidSearchURL, Listing
import main

URL = "https://rent.591.com.tw/list?region=1"


def make(listing_id: str) -> Listing:
    return Listing(
        id=listing_id, title="測試", price="20,000", size="7坪", kind="獨立套房",
        floor="3F/9F", address="中山區-測試路", metro=None,
        url=f"https://rent.591.com.tw/{listing_id}",
    )


@pytest.fixture
def fake_fetch(monkeypatch):
    def install(listings):
        monkeypatch.setattr(main, "fetch", lambda url, pages=3: listings)
    return install


def test_add_records_name_url_and_seen(fake_fetch):
    fake_fetch([make("1"), make("2")])
    subs = {"subs": []}
    text, changed = main.handle_command(AddSub(name="中山套房", url=URL), subs)

    assert changed is True
    assert len(subs["subs"]) == 1
    sub = subs["subs"][0]
    assert sub["name"] == "中山套房"
    assert sub["url"] == URL
    assert sub["seen"] == ["1", "2"]      # 現有物件記為基準，不會隔天全推
    assert sub["last_count"] == 2
    assert "已新增" in text and "中山套房" in text and "2 筆" in text


def test_add_without_name_gets_numbered_default(fake_fetch):
    # 第二筆刻意用不同網址：這個測試驗的是自動編號，不是重複網址的處理
    fake_fetch([make("1")])
    subs = {"subs": [{"name": "既有", "url": URL, "seen": [], "last_count": 0}]}
    main.handle_command(AddSub(name="", url=f"{URL}&section=5"), subs)
    assert subs["subs"][1]["name"] == "條件 2"


def test_add_warns_when_zero_results(fake_fetch):
    # 0 筆是合法結果（條件過嚴），仍然新增但要提醒
    fake_fetch([])
    subs = {"subs": []}
    text, changed = main.handle_command(AddSub(name="太嚴", url=URL), subs)
    assert changed is True
    assert "0 筆" in text
    assert "過嚴" in text or "有誤" in text


def test_add_warns_when_results_hit_page_cap(fake_fetch):
    fake_fetch([make(str(i)) for i in range(90)])
    subs = {"subs": []}
    text, _ = main.handle_command(AddSub(name="太寬", url=URL), subs)
    assert "收緊" in text


def test_add_rejects_duplicate_url(monkeypatch):
    monkeypatch.setattr(main, "fetch", lambda url, pages=3: pytest.fail("重複網址不該再抓一次"))
    subs = {"subs": [{"name": "既有", "url": URL, "seen": [], "last_count": 1}]}

    text, changed = main.handle_command(AddSub(name="重複", url=URL), subs)

    assert changed is False
    assert len(subs["subs"]) == 1
    assert "已經在監控中" in text


def test_add_rejects_invalid_url(monkeypatch):
    def boom(url, pages=3):
        raise InvalidSearchURL("bad")
    monkeypatch.setattr(main, "fetch", boom)
    subs = {"subs": []}
    text, changed = main.handle_command(AddSub(name="壞", url=URL), subs)
    assert changed is False
    assert subs["subs"] == []
    assert "無法" in text or "失敗" in text


def test_list_shows_numbered_names_and_counts():
    subs = {"subs": [
        {"name": "中山套房", "url": URL, "seen": [], "last_count": 47},
        {"name": "大安電梯", "url": URL, "seen": [], "last_count": 12},
    ]}
    text, changed = main.handle_command(ListSubs(), subs)
    assert changed is False
    assert "1. 中山套房（47 筆）" in text
    assert "2. 大安電梯（12 筆）" in text


def test_list_when_empty():
    text, changed = main.handle_command(ListSubs(), {"subs": []})
    assert changed is False
    assert "尚未" in text


def test_delete_removes_by_one_based_index():
    subs = {"subs": [
        {"name": "甲", "url": URL, "seen": [], "last_count": 1},
        {"name": "乙", "url": URL, "seen": [], "last_count": 2},
    ]}
    text, changed = main.handle_command(DeleteSub(index=2), subs)
    assert changed is True
    assert [s["name"] for s in subs["subs"]] == ["甲"]
    assert "乙" in text


def test_delete_out_of_range_changes_nothing():
    subs = {"subs": [{"name": "甲", "url": URL, "seen": [], "last_count": 1}]}
    text, changed = main.handle_command(DeleteSub(index=5), subs)
    assert changed is False
    assert len(subs["subs"]) == 1
    assert "沒有" in text


def test_help_mentions_all_three_operations():
    text, changed = main.handle_command(Help(), {"subs": []})
    assert changed is False
    assert "591" in text and "清單" in text and "刪除" in text


# ---- HTTP 層 ----

def test_webhook_rejects_bad_signature(monkeypatch):
    monkeypatch.setattr(main, "verify_signature", lambda body, sig: False)
    client = main.app.test_client()
    response = client.post("/webhook", json={"events": []}, headers={"X-Line-Signature": "nope"})
    assert response.status_code == 400


def test_webhook_accepts_valid_signature(monkeypatch):
    monkeypatch.setattr(main, "verify_signature", lambda body, sig: True)
    monkeypatch.setattr(main, "load_subs", lambda: {"subs": []})
    client = main.app.test_client()
    response = client.post("/webhook", json={"events": []}, headers={"X-Line-Signature": "ok"})
    assert response.status_code == 200


def test_health_check():
    assert main.app.test_client().get("/").status_code == 200


def test_webhook_returns_200_even_when_handling_an_event_raises(monkeypatch):
    # 個別事件失敗不能拖垮整批：LINE 收不到 200 會重送整批事件
    monkeypatch.setattr(main, "verify_signature", lambda body, sig: True)
    monkeypatch.setattr(main, "load_subs", lambda: {"subs": []})

    def boom(command, subs):
        raise RuntimeError("處理指令時炸了")

    monkeypatch.setattr(main, "handle_command", boom)
    monkeypatch.setattr(main, "reply", lambda token, text: None)

    response = main.app.test_client().post(
        "/webhook",
        json={"events": [{"type": "message", "message": {"type": "text", "text": "清單"}, "replyToken": "t"}]},
        headers={"X-Line-Signature": "ok"},
    )
    assert response.status_code == 200


def test_webhook_saves_when_subscription_added(monkeypatch):
    monkeypatch.setattr(main, "verify_signature", lambda body, sig: True)
    monkeypatch.setattr(main, "load_subs", lambda: {"subs": []})
    monkeypatch.setattr(main, "fetch", lambda url, pages=3: [])
    monkeypatch.setattr(main, "reply", lambda token, text: None)
    saved = []
    monkeypatch.setattr(main, "save_subs", saved.append)

    main.app.test_client().post(
        "/webhook",
        json={"events": [{"type": "message", "message": {"type": "text", "text": URL}, "replyToken": "t"}]},
        headers={"X-Line-Signature": "ok"},
    )
    assert len(saved) == 1, "新增訂閱後必須寫回，否則使用者的設定會消失"


def test_webhook_does_not_save_for_readonly_command(monkeypatch):
    monkeypatch.setattr(main, "verify_signature", lambda body, sig: True)
    monkeypatch.setattr(main, "load_subs", lambda: {"subs": []})
    monkeypatch.setattr(main, "reply", lambda token, text: None)
    monkeypatch.setattr(main, "save_subs", lambda subs: pytest.fail("唯讀指令不該寫回"))

    response = main.app.test_client().post(
        "/webhook",
        json={"events": [{"type": "message", "message": {"type": "text", "text": "清單"}, "replyToken": "t"}]},
        headers={"X-Line-Signature": "ok"},
    )
    assert response.status_code == 200


def test_webhook_signature_wiring_end_to_end(monkeypatch):
    # 不 mock verify_signature，用真實 HMAC 驗證路由與簽章之間的接線。
    # 關鍵是簽章必須對「實際送出的那份 bytes」計算。
    import base64
    import hashlib
    import hmac as hmac_mod

    monkeypatch.setenv("LINE_CHANNEL_SECRET", "wiring-secret")
    monkeypatch.setattr(main, "load_subs", lambda: {"subs": []})

    body = b'{"events":[]}'
    digest = hmac_mod.new(b"wiring-secret", body, hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode()

    client = main.app.test_client()
    ok = client.post("/webhook", data=body, content_type="application/json",
                     headers={"X-Line-Signature": signature})
    bad = client.post("/webhook", data=body, content_type="application/json",
                      headers={"X-Line-Signature": "d3Jvbmc="})

    assert ok.status_code == 200
    assert bad.status_code == 400


def test_add_reports_failure_when_fetch_raises_unexpectedly(monkeypatch):
    def boom(url, pages=3):
        raise RuntimeError("網路炸了")

    monkeypatch.setattr(main, "fetch", boom)
    subs = {"subs": []}
    text, changed = main.handle_command(AddSub(name="測試", url=URL), subs)

    assert changed is False
    assert subs["subs"] == [], "抓取失敗不得留下半殘的訂閱"
    assert "失敗" in text
