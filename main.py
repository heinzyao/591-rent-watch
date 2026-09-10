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


def run_daily(subs: dict) -> tuple[list[str], bool]:
    """跑完所有訂閱，回傳 (要推播的訊息, 是否判定為解析失敗)。

    判定為失敗時呼叫端不得寫回 subs —— 若 591 改版導致解析全空而我們照樣
    更新了 seen，隔天修好時會湧出一整批重複推播。
    """
    groups: list[tuple[str, list]] = []
    errors: list[str] = []
    fetched_counts: list[int] = []

    for sub in subs["subs"]:
        try:
            listings = fetch(sub["url"], pages=PAGES)
        except Exception:
            log.exception("訂閱「%s」抓取失敗", sub["name"])
            errors.append(sub["name"])
            continue

        seen = set(sub["seen"])
        fetched_counts.append(len(listings))
        groups.append((sub["name"], diff(listings, seen)))
        sub["seen"] = sub["seen"] + [item.id for item in listings if item.id not in seen]
        sub["last_count"] = len(listings)

    # 所有成功抓取的訂閱都回 0 筆 —— 正常情況下不可能同時歸零，判定為 591 改版。
    # 只有一組訂閱時這個判斷會把「條件真的沒物件」誤報為改版，但誤報方向是安全的
    # （只是多發一則告警，不會動到 seen）。
    if fetched_counts and not any(fetched_counts):
        return [], True

    messages = format_new_listings(groups)
    if errors and messages:
        messages[-1] += f"\n\n⚠️ 以下條件本次抓取失敗，將於明日重試：{'、'.join(errors)}"

    return messages, False


@app.post("/cron")
def cron() -> tuple[str, int]:
    # ponytail: 共享密鑰擋 /cron。Service 必須公開（LINE webhook 要打得到），
    # 所以無法靠 Cloud Run IAM 保護。若日後有多個排程來源，改用 Cloud Scheduler
    # OIDC + Google ID token 驗證。
    if request.headers.get("X-Cron-Key") != os.environ["CRON_KEY"]:
        return "forbidden", 403

    subs = load_subs()
    messages, failed = run_daily(subs)

    if failed:
        broadcast("⚠️ 591 解析失敗，所有條件都抓不到物件，網站可能已改版。")
        return "parse failure", 500

    if messages:
        broadcast_all(messages)      # 失敗會往外拋，下面的 save_subs 就不會執行

    save_subs(subs)
    return "ok", 200
