import pytest

from rent591 import InvalidSearchURL, Listing, diff, normalize_url


def make(listing_id: str) -> Listing:
    return Listing(
        id=listing_id, title="測試物件", price="20,000", size="7坪",
        kind="獨立套房", floor="3F/9F", address="中山區-測試路",
        metro=None, url=f"https://rent.591.com.tw/{listing_id}",
    )


def test_normalize_url_forces_newest_sort():
    result = normalize_url("https://rent.591.com.tw/list?region=1", page=1)
    assert "sort=posttime_desc" in result
    assert "region=1" in result


def test_normalize_url_overrides_existing_sort():
    result = normalize_url("https://rent.591.com.tw/list?region=1&sort=money_asc", page=1)
    assert "money_asc" not in result
    assert "sort=posttime_desc" in result


def test_normalize_url_sets_page():
    assert "page=2" in normalize_url("https://rent.591.com.tw/list?region=1", page=2)


def test_normalize_url_rejects_foreign_host():
    # 使用者貼進來的網址是外部輸入，非 591 網域一律拒絕（SSRF 防線）
    with pytest.raises(InvalidSearchURL):
        normalize_url("https://evil.example.com/list?region=1", page=1)


def test_normalize_url_rejects_lookalike_host():
    with pytest.raises(InvalidSearchURL):
        normalize_url("https://rent.591.com.tw.evil.com/list", page=1)


def test_normalize_url_rejects_non_http_scheme():
    with pytest.raises(InvalidSearchURL):
        normalize_url("file:///etc/passwd", page=1)


def test_diff_returns_only_unseen():
    listings = [make("1"), make("2"), make("3")]
    assert [x.id for x in diff(listings, {"2"})] == ["1", "3"]


def test_diff_with_empty_seen_returns_all():
    listings = [make("1"), make("2")]
    assert len(diff(listings, set())) == 2


def test_diff_preserves_order():
    listings = [make("9"), make("1"), make("5")]
    assert [x.id for x in diff(listings, set())] == ["9", "1", "5"]
