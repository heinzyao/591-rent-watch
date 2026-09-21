"""Flask app：LINE webhook 與每日排程進入點。"""

from __future__ import annotations

import hmac
import logging
import os

from flask import Flask, request

from commands import AddSub, Command, DeleteSub, ListSubs, parse_command
from notify import broadcast, broadcast_all, format_new_listings, reply, verify_signature
from rent591 import PAGE_SIZE, InvalidSearchURL, diff, fetch
from store import load_subs, save_subs

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# 啟動時就檢查，讓設定錯誤出現在部署當下的終端機，而不是隔天早上的 log。
# gunicorn 起不來 → revision 不 ready → 流量不會切過來，舊版繼續服務。
for _var in ("GCS_BUCKET", "CRON_KEY", "LINE_CHANNEL_SECRET", "LINE_CHANNEL_ACCESS_TOKEN"):
    if not os.environ.get(_var):
        raise RuntimeError(f"缺少必要環境變數：{_var}")

PAGES = int(os.environ.get("PAGES", "3"))
PAGE_CAP = PAGES * PAGE_SIZE

HELP_TEXT = (
    "把 591 搜尋頁的網址貼給我就會開始監控，每天 9:00、21:00 推播新上架的物件。\n\n"
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
        if any(s["url"] == command.url for s in subs["subs"]):
            return "這組條件已經在監控中，輸入「清單」可以查看。", False
        # ponytail: 上限 10 組。/cron 序列跑完所有訂閱，超過這個數量會撞上
        # Cloud Run 的請求逾時且失敗無聲。要支援更多就得改成並行抓取。
        if len(subs["subs"]) >= 10:
            return "條件數已達上限 10 組，請先刪除不需要的條件。", False
        try:
            # ponytail: 同步抓取。新增訂閱時會同步抓 3 頁（約 2–3 秒）才回覆。LINE 對 webhook 回應時間沒有硬性 1 秒限制，逾時會重送。若開始出現重送，改成先 reply「處理中」再背景補抓。
            listings = fetch(command.url, pages=PAGES)
        except InvalidSearchURL:
            return "無法辨識這個網址，請從 rent.591.com.tw 的搜尋結果頁複製。", False
        # ponytail: 所有抓取失敗都回同一句話。log.exception 已保留完整 traceback 供排查；
        # 若日後需要區分逾時／解析錯誤／程式錯誤再拆開。
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

        text = f"✅ 已新增「{name}」\n目前符合 {len(listings)} 筆，已記錄為基準，之後只推新上架的物件。"
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
        try:
            command = parse_command(event["message"]["text"])
            text, changed = handle_command(command, subs)
            dirty = dirty or changed
            reply(event["replyToken"], text)
        except Exception:
            log.exception("處理事件失敗")
            continue

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
    # ponytail: 只有一組訂閱時，該組合法的 0 筆會被誤判為改版。誤報方向是安全的
    # （只多發一則告警，不會動到 seen）。若要消除誤報，改成比對該訂閱近幾次
    # last_count 的歷史趨勢，而非只看單次結果。
    if fetched_counts and not any(fetched_counts):
        return [], True

    messages = format_new_listings(groups)
    if errors:
        # 獨立一則，不接在最後一則尾巴——那則可能已經接近 4800 字元的切割上限
        messages.append(f"⚠️ 以下條件本次抓取失敗，將於下次重試：{'、'.join(errors)}")

    return messages, False


@app.post("/cron")
def cron() -> tuple[str, int]:
    # ponytail: 共享密鑰擋 /cron。Service 必須公開（LINE webhook 要打得到），
    # 所以無法靠 Cloud Run IAM 保護。若日後有多個排程來源，改用 Cloud Scheduler
    # OIDC + Google ID token 驗證。
    if not hmac.compare_digest(
        request.headers.get("X-Cron-Key", "").encode("utf-8", "replace"),
        os.environ["CRON_KEY"].encode(),
    ):
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
