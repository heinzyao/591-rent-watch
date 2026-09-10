"""把 LINE 訊息文字轉成指令。純函式，無外部相依。

只有三種操作，所以不用 slash 語法、不用狀態機、不接 LLM。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 只認搜尋列表頁；物件詳情頁（rent.591.com.tw/12345678）不是搜尋條件
SEARCH_URL_RE = re.compile(r"https://rent\.591\.com\.tw/list\?\S+")
DELETE_RE = re.compile(r"^(?:刪除|del)\s*(\d+)$", re.IGNORECASE)
LIST_WORDS = {"清單", "列表", "list"}


@dataclass(frozen=True)
class AddSub:
    name: str   # 空字串代表使用者沒給名稱，由呼叫端命名
    url: str


@dataclass(frozen=True)
class ListSubs:
    pass


@dataclass(frozen=True)
class DeleteSub:
    index: int  # 1-based，對應「清單」顯示的編號


@dataclass(frozen=True)
class Help:
    pass


Command = AddSub | ListSubs | DeleteSub | Help


def parse_command(text: str) -> Command:
    text = (text or "").strip()

    match = SEARCH_URL_RE.search(text)
    if match:
        name = (text[: match.start()] + " " + text[match.end() :]).strip()
        return AddSub(name=name, url=match.group(0))

    if text.lower() in LIST_WORDS:
        return ListSubs()

    delete = DELETE_RE.match(text)
    if delete:
        return DeleteSub(index=int(delete.group(1)))

    return Help()
