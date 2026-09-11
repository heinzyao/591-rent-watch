import pytest

from rent591 import Listing
import main

URL = "https://rent.591.com.tw/list?region=1"


def make(listing_id: str) -> Listing:
    return Listing(
        id=listing_id, title="測試", price="20,000", size="7坪", kind="獨立套房",
        floor="3F/9F", address="中山區-測試路", metro=None,
        url=f"https://rent.591.com.tw/{listing_id}",
    )


def sub(name: str, seen: list[str]) -> dict:
    return {"name": name, "url": URL, "seen": list(seen), "last_count": len(seen)}


@pytest.fixture
def fetch_returns(monkeypatch):
    def install(mapping):
        """mapping: 訂閱名稱 -> 回傳的 listings 或要拋出的例外"""
        calls = {"n": 0}
        names = list(mapping)

        def fake(url, pages=3):
            result = mapping[names[calls["n"]]]
            calls["n"] += 1
            if isinstance(result, Exception):
                raise result
            return result
        monkeypatch.setattr(main, "fetch", fake)
    return install


def test_new_listings_are_collected_and_seen_updated(fetch_returns):
    fetch_returns({"甲": [make("1"), make("2"), make("3")]})
    subs = {"subs": [sub("甲", ["1"])]}

    messages, failed = main.run_daily(subs)

    assert failed is False
    assert len(messages) == 1
    assert "今日新物件 2 筆" in messages[0]
    assert subs["subs"][0]["seen"] == ["1", "2", "3"]
    assert subs["subs"][0]["last_count"] == 3


def test_no_new_listings_produces_no_messages(fetch_returns):
    fetch_returns({"甲": [make("1")]})
    subs = {"subs": [sub("甲", ["1"])]}
    messages, failed = main.run_daily(subs)
    assert messages == []
    assert failed is False


def test_seen_is_independent_per_subscription(fetch_returns):
    # 同一物件出現在兩組條件時，兩組各推一次（正確語意，且省掉跨組去重）
    fetch_returns({"甲": [make("1")], "乙": [make("1")]})
    subs = {"subs": [sub("甲", []), sub("乙", [])]}
    messages, failed = main.run_daily(subs)
    assert "今日新物件 2 筆" in messages[0]
    assert subs["subs"][0]["seen"] == ["1"]
    assert subs["subs"][1]["seen"] == ["1"]


def test_single_empty_group_is_normal_not_failure(fetch_returns):
    # 單組 0 筆是合法結果（條件過嚴），不是解析失敗
    fetch_returns({"甲": [make("1")], "乙": []})
    subs = {"subs": [sub("甲", []), sub("乙", [])]}
    messages, failed = main.run_daily(subs)
    assert failed is False
    assert "甲" in messages[0]


def test_all_groups_empty_is_treated_as_parse_failure(fetch_returns):
    # 多組條件同時歸零，正常情況不可能發生，判定為 591 改版
    fetch_returns({"甲": [], "乙": []})
    subs = {"subs": [sub("甲", ["old"]), sub("乙", ["old"])]}
    messages, failed = main.run_daily(subs)
    assert failed is True
    assert subs["subs"][0]["seen"] == ["old"]   # 失敗時不得更動 seen
    assert subs["subs"][0]["last_count"] == 0, "失敗時的就地修改不得落地——這裡鎖住現況，呼叫端必須不寫回"


def test_no_subscriptions_is_not_a_failure():
    messages, failed = main.run_daily({"subs": []})
    assert messages == []
    assert failed is False


def test_failed_group_is_skipped_and_others_continue(fetch_returns):
    fetch_returns({"甲": [make("1")], "乙": RuntimeError("timeout")})
    subs = {"subs": [sub("甲", []), sub("乙", ["old"])]}
    messages, failed = main.run_daily(subs)

    assert failed is False
    assert "甲" in messages[0]
    assert "乙" in messages[-1]                  # 訊息末尾附註哪組失敗
    assert subs["subs"][1]["seen"] == ["old"]    # 失敗組不更新 seen


# ---- HTTP 層 ----

def test_cron_rejects_wrong_key(monkeypatch):
    monkeypatch.setenv("CRON_KEY", "secret")
    response = main.app.test_client().post("/cron", headers={"X-Cron-Key": "wrong"})
    assert response.status_code == 403


def test_cron_rejects_non_ascii_key(monkeypatch):
    # hmac.compare_digest 對非 ASCII 的 str 會拋 TypeError，而這個 header
    # 來自公開端點，任何人都能送。必須回 403 而不是 500。
    monkeypatch.setenv("CRON_KEY", "secret")
    response = main.app.test_client().post("/cron", headers={"X-Cron-Key": "café"})
    assert response.status_code == 403


def test_cron_rejects_missing_key(monkeypatch):
    monkeypatch.setenv("CRON_KEY", "secret")
    assert main.app.test_client().post("/cron").status_code == 403


def test_cron_returns_500_on_parse_failure(monkeypatch):
    monkeypatch.setenv("CRON_KEY", "secret")
    monkeypatch.setattr(main, "load_subs", lambda: {"subs": []})
    monkeypatch.setattr(main, "run_daily", lambda subs: ([], True))
    sent = []
    monkeypatch.setattr(main, "broadcast", lambda text: sent.append(text))
    monkeypatch.setattr(main, "save_subs", lambda subs: pytest.fail("失敗時不該寫回"))

    response = main.app.test_client().post("/cron", headers={"X-Cron-Key": "secret"})
    assert response.status_code == 500
    assert "改版" in sent[0]


def test_cron_saves_only_after_successful_broadcast(monkeypatch):
    monkeypatch.setenv("CRON_KEY", "secret")
    monkeypatch.setattr(main, "load_subs", lambda: {"subs": []})
    monkeypatch.setattr(main, "run_daily", lambda subs: (["訊息"], False))
    def boom(texts):
        raise RuntimeError("LINE down")
    monkeypatch.setattr(main, "broadcast_all", boom)
    monkeypatch.setattr(main, "save_subs", lambda subs: pytest.fail("推播失敗時不該寫回"))

    response = main.app.test_client().post("/cron", headers={"X-Cron-Key": "secret"})
    assert response.status_code == 500


def test_cron_saves_after_successful_broadcast(monkeypatch):
    monkeypatch.setenv("CRON_KEY", "secret")
    monkeypatch.setattr(main, "load_subs", lambda: {"subs": []})
    monkeypatch.setattr(main, "run_daily", lambda subs: (["訊息"], False))
    monkeypatch.setattr(main, "broadcast_all", lambda texts: None)
    saved = []
    monkeypatch.setattr(main, "save_subs", saved.append)

    response = main.app.test_client().post("/cron", headers={"X-Cron-Key": "secret"})

    assert response.status_code == 200
    assert len(saved) == 1, "推播成功後必須寫回，否則隔天會重推同一批物件"


def test_all_groups_failing_still_notifies_the_user(fetch_returns):
    # 591 整站打不通時，使用者必須收到訊息，不能跟「今天沒新物件」無法區分
    fetch_returns({"甲": RuntimeError("timeout"), "乙": RuntimeError("timeout")})
    subs = {"subs": [sub("甲", ["old"]), sub("乙", ["old"])]}

    messages, failed = main.run_daily(subs)

    assert messages, "全部抓取失敗卻沒有任何訊息，使用者無從得知排程壞了"
    assert "甲" in messages[-1] and "乙" in messages[-1]


def test_failure_note_survives_when_no_group_has_new_listings(fetch_returns):
    # 一組失敗、其他組今天沒新物件（最常見的情況）：失敗通知不能被丟掉
    fetch_returns({"甲": [make("1")], "乙": RuntimeError("boom")})
    subs = {"subs": [sub("甲", ["1"]), sub("乙", ["old"])]}

    messages, failed = main.run_daily(subs)

    assert failed is False
    assert messages, "甲沒有新物件不代表乙的失敗可以不通知"
    assert "乙" in messages[-1]
