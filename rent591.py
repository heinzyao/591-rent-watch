"""591 租屋網列表頁的抓取與解析。不依賴 Flask 或 LINE。"""

from __future__ import annotations

import re
import ssl
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util import create_urllib3_context


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


def _txt(el: Tag | None) -> str:
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

        url = link.get("href")
        if not url:
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
                url=url,
            )
        )

    return listings


ALLOWED_HOST = "rent.591.com.tw"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
PAGE_SIZE = 30


class InvalidSearchURL(ValueError):
    """搜尋網址不是合法的 591 租屋列表網址。"""


def normalize_url(search_url: str, page: int) -> str:
    """驗證網域，強制最新上架排序，並設定頁碼。

    使用者貼進來的網址是外部輸入，必須確認 host 正好是 rent.591.com.tw，
    否則這個函式會變成任意網址的抓取代理（SSRF）。
    """
    parts = urlparse(search_url)
    if (
        parts.scheme not in ("http", "https")
        or parts.hostname != ALLOWED_HOST
        or not parts.path.startswith("/list")
    ):
        raise InvalidSearchURL(f"只接受 https://{ALLOWED_HOST}/list 開頭的網址")

    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in ("sort", "page")]
    query.append(("sort", "posttime_desc"))
    query.append(("page", str(page)))
    return urlunparse(parts._replace(query=urlencode(query), fragment=""))


def _ssl_context() -> ssl.SSLContext:
    """591 的憑證鏈不符 RFC 5280 嚴格要求：中間憑證 TWCA Secure SSL CA 缺少
    Subject Key Identifier，Python 3.13+ / OpenSSL 3.5+ 預設的 VERIFY_X509_STRICT
    會直接拒絕。這裡只關掉這一項格式檢查，信任鏈、主機名與有效期驗證全部保留。
    """
    context = create_urllib3_context()
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def _make_session() -> requests.Session:
    """建立帶有放寬憑證格式檢查的 Session。"""
    context = _ssl_context()

    class _Adapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            kwargs["ssl_context"] = context
            return super().init_poolmanager(*args, **kwargs)

    session = requests.Session()
    session.mount("https://", _Adapter())
    return session


_session = _make_session()


def _get(url: str) -> str:
    """抓單一頁面，失敗時重試一次。"""
    for attempt in range(2):
        try:
            response = _session.get(
                url, headers={"User-Agent": USER_AGENT}, timeout=20
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            if attempt == 1:
                raise
            time.sleep(1)
    raise AssertionError("unreachable")


def fetch(search_url: str, pages: int = 3) -> list[Listing]:
    """抓取前 pages 頁並合併去重。

    第一頁失敗即整體失敗；後續頁失敗則以已取得的頁數繼續，
    寧可少抓幾筆，也不要因為第 3 頁逾時就整組訂閱當掉。
    """
    merged: dict[str, Listing] = {}

    for page in range(1, pages + 1):
        try:
            html = _get(normalize_url(search_url, page))
        except requests.RequestException:
            if page == 1:
                raise
            break

        page_listings = parse(html)
        for listing in page_listings:
            merged.setdefault(listing.id, listing)

        # 未滿一頁代表已經是最後一頁，不必再往下翻
        if len(page_listings) < PAGE_SIZE:
            break

    return list(merged.values())


def diff(listings: list[Listing], seen: set[str]) -> list[Listing]:
    """回傳 id 不在 seen 中的物件，保持原順序（最新上架在前）。"""
    return [listing for listing in listings if listing.id not in seen]
