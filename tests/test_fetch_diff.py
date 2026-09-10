import pytest

from rent591 import InvalidSearchURL, Listing, diff, normalize_url


def make(listing_id: str) -> Listing:
    return Listing(
        id=listing_id, title="測試物件", price="20,000", size="7坪",
        kind="獨立套房", floor="3F/9F", address="中山區-測試路",
        metro=None, url=f"https://rent.591.com.tw/{listing_id}",
    )


def _fake_page(ids: list[str]) -> str:
    """組出最小可解析的列表頁 HTML，只含 parse() 必要的結構。"""
    items = "".join(
        f'''<div class="item" data-id="{i}">
          <div class="item-info-title"><a class="link" href="https://rent.591.com.tw/{i}">物件 {i}</a></div>
          <div class="item-info-txt"><i class="ic-house house-home"></i>
            <span>獨立套房</span><span>7坪</span><span>3F/9F</span></div>
          <div class="item-info-txt"><i class="ic-house house-place"></i><span>中山區-測試路</span></div>
          <div class="item-info-price"><strong>20,000</strong></div>
        </div>'''
        for i in ids
    )
    return f"<html><body>{items}</body></html>"


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


def test_normalize_url_rejects_non_list_path():
    # 這個函式只用於抓搜尋列表頁，591 網域下的其他路徑一律拒絕
    with pytest.raises(InvalidSearchURL):
        normalize_url("https://rent.591.com.tw/21977665", page=1)


def test_diff_returns_only_unseen():
    listings = [make("1"), make("2"), make("3")]
    assert [x.id for x in diff(listings, {"2"})] == ["1", "3"]


def test_diff_with_empty_seen_returns_all():
    listings = [make("1"), make("2")]
    assert len(diff(listings, set())) == 2


def test_diff_preserves_order():
    listings = [make("9"), make("1"), make("5")]
    assert [x.id for x in diff(listings, set())] == ["9", "1", "5"]


def test_ssl_context_keeps_verification_but_drops_strict_format_check():
    # 591 的憑證鏈缺 Subject Key Identifier，必須關掉 VERIFY_X509_STRICT 才連得上，
    # 但憑證驗證本身絕不能關掉——這個測試就是防止有人日後改成 verify=False
    import ssl

    from rent591 import _ssl_context

    context = _ssl_context()
    assert not (context.verify_flags & ssl.VERIFY_X509_STRICT)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_session_actually_uses_the_hardened_adapter():
    # 上一個測試只檢查工廠函式的輸出，這個測試確認實際發請求的 session
    # 真的掛上了那個 adapter，且沒有在 session 層級被放寬
    import rent591

    assert rent591._session.verify is not False
    adapter = rent591._session.get_adapter("https://rent.591.com.tw")
    assert adapter is not rent591._session.get_adapter("http://example.com"), (
        "https 應該掛的是自訂 adapter，不是預設的那個"
    )


def test_fetch_merges_pages_and_dedupes_by_id(monkeypatch):
    import rent591

    pages = {
        1: _fake_page([f"1{i:02d}" for i in range(30)]),
        2: _fake_page(["100", "200"]),  # 100 與第一頁重複
    }
    calls = []

    def fake_get(url):
        page = int(url.rsplit("page=", 1)[1])
        calls.append(page)
        return pages[page]

    monkeypatch.setattr(rent591, "_get", fake_get)
    result = rent591.fetch("https://rent.591.com.tw/list?region=1", pages=2)

    ids = [x.id for x in result]
    assert len(ids) == len(set(ids)), "跨頁重複的物件必須去重"
    assert "200" in ids
    assert calls == [1, 2]


def test_fetch_stops_early_when_page_not_full(monkeypatch):
    import rent591

    calls = []

    def fake_get(url):
        calls.append(int(url.rsplit("page=", 1)[1]))
        return _fake_page(["1", "2"])  # 只有 2 筆，未滿一頁

    monkeypatch.setattr(rent591, "_get", fake_get)
    rent591.fetch("https://rent.591.com.tw/list?region=1", pages=3)

    assert calls == [1], "未滿一頁代表已是最後一頁，不該繼續翻頁"


def test_fetch_raises_when_first_page_fails(monkeypatch):
    import requests

    import rent591

    def fake_get(url):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(rent591, "_get", fake_get)
    with pytest.raises(requests.RequestException):
        rent591.fetch("https://rent.591.com.tw/list?region=1", pages=3)


def test_fetch_keeps_earlier_pages_when_later_page_fails(monkeypatch):
    import requests

    import rent591

    def fake_get(url):
        if url.endswith("page=1"):
            return _fake_page([f"1{i:02d}" for i in range(30)])
        raise requests.ConnectionError("第二頁掛了")

    monkeypatch.setattr(rent591, "_get", fake_get)
    result = rent591.fetch("https://rent.591.com.tw/list?region=1", pages=3)

    assert len(result) == 30, "後續頁失敗時應保留已取得的頁，而不是整組失敗"
