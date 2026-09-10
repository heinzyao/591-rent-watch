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
    fake_fetch([make("1")])
    subs = {"subs": [{"name": "既有", "url": URL, "seen": [], "last_count": 0}]}
    main.handle_command(AddSub(name="", url=URL), subs)
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
