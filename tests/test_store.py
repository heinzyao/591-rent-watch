from store import SEEN_LIMIT, trim_seen


def test_trim_keeps_short_list_intact():
    assert trim_seen(["1", "2", "3"]) == ["1", "2", "3"]


def test_trim_caps_at_limit():
    assert len(trim_seen([str(i) for i in range(1500)])) == SEEN_LIMIT


def test_trim_keeps_the_newest_entries():
    # 新的 id 附加在尾端，所以要保留尾端
    result = trim_seen([str(i) for i in range(1500)])
    assert result[-1] == "1499"
    assert result[0] == "500"


def test_trim_handles_empty():
    assert trim_seen([]) == []
