"""把 LINE 訊息文字轉成指令。純函式，無外部相依。

只有三種操作，所以不用 slash 語法、不用狀態機、不接 LLM。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 只認搜尋列表頁；物件詳情頁（rent.591.com.tw/12345678）不是搜尋條件
# [!-~] 是所有可見的 ASCII 字元，天然排除空白、中文與全形標點。
# 不能改用 \w 或排除半形逗號——591 的 section=5,7 這類參數需要它們。
SEARCH_URL_RE = re.compile(r"https://rent\.591\.com\.tw/list\?[!-~]+")
# 網址後緊接的標點不屬於網址本身。中文輸入常見「網址，名稱」不留空格的寫法。
TRAILING_PUNCT = "，。！？、；：,.!?;:"
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
        url = match.group(0).rstrip(TRAILING_PUNCT)
        name = " ".join((text[: match.start()] + " " + text[match.end() :]).split())
        name = name.strip(TRAILING_PUNCT).strip()
        # 一則訊息只處理一個網址；殘留的第二個網址不該變成名稱
        if "https://" in name:
            name = ""
        return AddSub(name=name, url=url)

    if text.lower() in LIST_WORDS:
        return ListSubs()

    delete = DELETE_RE.match(text)
    if delete:
        return DeleteSub(index=int(delete.group(1)))

    return Help()
