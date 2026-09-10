"""591 租屋網列表頁的抓取與解析。不依賴 Flask 或 LINE。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class Listing:
    id: str
    title: str
    price: str          # "25,000"
    size: str           # "7坪"
    kind: str           # "獨立套房"
    floor: str          # "3F/9F"、"頂樓加蓋/4F"
    address: str        # "中山區-林森北路"
    metro: str | None   # "距雙連 501公尺"，非近捷運物件為 None
    url: str


def _txt(el) -> str:
    """取出元素的文字並壓縮空白。元素不存在時回空字串。"""
    if el is None:
        return ""
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def parse(html: str) -> list[Listing]:
    """把列表頁 HTML 解析成 Listing 清單。無物件時回空清單。"""
    soup = BeautifulSoup(html, "lxml")
    listings: list[Listing] = []

    for item in soup.select("div.item[data-id]"):
        link = item.select_one(".item-info-title a.link")
        if link is None:
            continue

        # 房型／坪數／樓層在同一個 item-info-txt 裡，順序不保證且樓層可能缺，
        # 因此以內容特徵取值而非 index。
        home = item.select_one(".item-info-txt:has(i.house-home)")
        spans = [_txt(s) for s in home.find_all("span", recursive=False)] if home else []
        kind = spans[0] if spans else ""
        size = next((s for s in spans if "坪" in s), "")
        floor = next((s for s in spans if re.search(r"\dF", s)), "")

        # 地址區塊的 span 數量不定（可能多一個「什麼都好談」之類的備註在前），
        # 地址固定是最後一個。
        place = item.select_one(".item-info-txt:has(i.house-place)")
        addr_spans = place.find_all("span", recursive=False) if place else []
        address = _txt(addr_spans[-1]) if addr_spans else ""

        listings.append(
            Listing(
                id=item["data-id"],
                title=_txt(link),
                price=_txt(item.select_one(".item-info-price strong")),
                size=size,
                kind=kind,
                floor=floor,
                address=address,
                metro=_txt(item.select_one(".item-info-txt:has(i.house-metro)")) or None,
                url=link["href"],
            )
        )

    return listings
