"""Flask app：LINE webhook 與每日排程進入點。"""

from __future__ import annotations

import logging
import os

from flask import Flask, request

from commands import AddSub, Command, DeleteSub, Help, ListSubs, parse_command
from notify import broadcast, broadcast_all, format_new_listings, reply, verify_signature
from rent591 import InvalidSearchURL, diff, fetch
from store import load_subs, save_subs

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

PAGES = int(os.environ.get("PAGES", "3"))
PAGE_CAP = PAGES * 30

HELP_TEXT = (
    "把 591 搜尋頁的網址貼給我就會開始監控，每天早上推播新上架的物件。\n\n"
    "・新增：貼上網址，可在前面加名稱\n"
    "　例：中山區套房 https://rent.591.com.tw/list?region=1\n"
    "・查看：清單\n"
    "・刪除：刪除 2"
)


def handle_command(command: Command, subs: dict) -> tuple[str, bool]:
    """套用指令到訂閱清單。回傳 (回覆文字, subs 是否被改動)。

    這個函式只操作傳入的 subs dict，不碰 GCS，因此可以完整測試。
    """
    if isinstance(command, AddSub):
        try:
            # ponytail: 同步抓取。新增訂閱時會同步抓 3 頁（約 2–3 秒）才回覆。LINE 對 webhook 回應時間沒有硬性 1 秒限制，逾時會重送。若開始出現重送，改成先 reply「處理中」再背景補抓。
            listings = fetch(command.url, pages=PAGES)
        except InvalidSearchURL:
            return "無法辨識這個網址，請從 rent.591.com.tw 的搜尋結果頁複製。", False
        except Exception:
            log.exception("新增訂閱時抓取失敗")
            return "抓取失敗，請稍後再試一次。", False

        name = command.name or f"條件 {len(subs['subs']) + 1}"
        subs["subs"].append({
            "name": name,
            "url": command.url,
            "seen": [item.id for item in listings],
            "last_count": len(listings),
        })

        text = f"✅ 已新增「{name}」\n目前符合 {len(listings)} 筆，已記錄為基準，明天起只推新上架的物件。"
        if not listings:
            text = f"✅ 已新增「{name}」\n但目前符合 0 筆，條件可能過嚴或網址有誤。"
        elif len(listings) >= PAGE_CAP:
            text += f"\n\n⚠️ 已達單次抓取上限 {PAGE_CAP} 筆，條件較寬，建議收緊以免漏接。"
        return text, True

    if isinstance(command, ListSubs):
        if not subs["subs"]:
            return "尚未設定任何搜尋條件。貼一個 591 搜尋頁網址給我就會開始監控。", False
        lines = [f"目前 {len(subs['subs'])} 組條件"]
        lines += [
            f"{i}. {sub['name']}（{sub['last_count']} 筆）"
            for i, sub in enumerate(subs["subs"], start=1)
        ]
        return "\n".join(lines), False

    if isinstance(command, DeleteSub):
        if not 1 <= command.index <= len(subs["subs"]):
            return f"沒有第 {command.index} 組條件。輸入「清單」看看目前有哪些。", False
        removed = subs["subs"].pop(command.index - 1)
        return f"🗑 已刪除「{removed['name']}」", True

    return HELP_TEXT, False


@app.get("/")
def health() -> tuple[str, int]:
    return "ok", 200


@app.post("/webhook")
def webhook() -> tuple[str, int]:
    if not verify_signature(request.get_data(), request.headers.get("X-Line-Signature")):
        return "bad signature", 400

    events = request.get_json(silent=True) or {}
    subs = load_subs()
    dirty = False

    for event in events.get("events", []):
        if event.get("type") != "message" or event["message"].get("type") != "text":
            continue
        command = parse_command(event["message"]["text"])
        text, changed = handle_command(command, subs)
        dirty = dirty or changed
        try:
            reply(event["replyToken"], text)
        except Exception:
            log.exception("回覆失敗")

    if dirty:
        save_subs(subs)

    # LINE 只要收到 200 就不會重送；個別事件的失敗已記在 log 裡
    return "ok", 200
