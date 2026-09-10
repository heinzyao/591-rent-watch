import re
from pathlib import Path

import pytest

from rent591 import Listing, parse

FIXTURE = Path(__file__).parent.parent / "docs" / "sample-list.html"


@pytest.fixture(scope="module")
def listings() -> list[Listing]:
    return parse(FIXTURE.read_text(encoding="utf-8"))


def test_parse_returns_all_30_listings(listings):
    assert len(listings) == 30


def test_parse_first_listing_fields(listings):
    first = listings[0]
    assert first.id == "21977665"
    assert first.price == "21,000"
    assert first.size == "7坪"
    assert first.kind == "獨立套房"
    assert first.floor == "3F/9F"
    assert first.address == "中山區-新生北路一段"
    assert first.metro == "距松江南京 280公尺"
    assert first.url == "https://rent.591.com.tw/21977665"


def test_every_listing_has_valid_url(listings):
    for item in listings:
        assert re.fullmatch(r"https://rent\.591\.com\.tw/\d+", item.url)


def test_required_fields_never_empty(listings):
    # metro 可以是 None（不是每個物件都近捷運），其餘欄位一律要有值
    for item in listings:
        for field in ("id", "title", "price", "size", "kind", "floor", "address", "url"):
            assert getattr(item, field), f"{item.id} 的 {field} 為空"


def test_parse_empty_page_returns_empty_list():
    # 頁數超界時 591 回傳沒有任何物件的頁面，必須回空清單而不是拋例外
    assert parse("<html><body><div class='empty'></div></body></html>") == []
