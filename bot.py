"""
Forward Tag Remover & Media Cloner Pro Bot (v1.0 - Production Edition)
100% Free & Zero External API Required — Works out of the box!
Supports: Render, VPS, Railway, Koyeb, Heroku, cPanel, Termux, Local PC

কিভাবে চালাবেন (২ভাবেই চালানো যাবে):
১. কোডের নিচে `DIRECT_BOT_TOKEN` এবং `DIRECT_ADMIN_ID`-এর ভেতরে সরাসরি টোকেন ও আইডি বসিয়ে চালাতে পারবেন।
২. অথবা Environment Variables-এ `BOT_TOKEN` এবং `ADMIN_ID` দিলেও অটোমেটিক চলবে!

ফিচারসমূহ:
- যেকোনো ছবি, ভিডিও, ফাইল, অডিও, ভয়েস, অ্যানিমেশন ও টেক্সট থেকে "Forwarded from..." ট্যাগ ১ সেকেন্ডে রিমুভ।
- কাস্টম ক্যাপশন মোড: নিজের চ্যানেলের লিংক বা টেক্সট সেট করে দেওয়ার সুবিধা।
- ক্যাপশন ক্লিনার মোড: আসল ক্যাপশন মুছে একদম ফ্রেশ মিডিয়া নেওয়া।
- ব্যাচ ফরওয়ার্ডিং সাপোর্ট: একসাথে একাধিক মেসেজ ফরোয়ার্ড করলেও সবগুলো ক্লিন করে আলাদা পাঠানো।
- টেলিগ্রাম ৯.৪ ফুল কালার বাটন (primary, success, danger)।
- স্বয়ংক্রিয় BotFather নেম ডিটেকশন ও রিয়েল-টাইম সিঙ্ক।
- সম্পূর্ণ ইন-বট অ্যাডমিন প্যানেল (ব্রডকাস্ট, ফোর্স-সাব চ্যানেল, স্ট্যাটাস)।
"""

import html
import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional, Set

import requests
from requests.adapters import HTTPAdapter

# ==============================================================================
# ⚙️ UNIVERSAL BOT CONFIGURATION (CODE + .ENV + ENVIRONMENT VARIABLES)
# ==============================================================================
DIRECT_BOT_TOKEN = ""   # যেমন: "1234567890:AAHxyz..." (Environment-এ দিলে এটি খালি রাখুন)
DIRECT_ADMIN_ID = ""    # যেমন: "123456789" (Environment-এ দিলে এটি খালি রাখুন)


def _load_dotenv_if_present() -> None:
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        env_path = os.path.join(base_dir, ".env")
        if os.path.isfile(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("\"'").strip()
                    if k and k not in os.environ:
                        os.environ[k] = v
    except Exception:
        pass


_load_dotenv_if_present()


def _resolve_config_value(env_keys: List[str], direct_val: str) -> str:
    cleaned_direct = (direct_val or "").strip()
    if cleaned_direct and not cleaned_direct.startswith("#"):
        return cleaned_direct
    for key in env_keys:
        val = os.getenv(key, "").strip()
        if val and not val.startswith("#"):
            return val
    return ""


BOT_TOKEN = _resolve_config_value(["BOT_TOKEN", "TELEGRAM_BOT_TOKEN"], DIRECT_BOT_TOKEN)
RAW_ADMIN_IDS = _resolve_config_value(["ADMIN_ID", "ADMIN_IDS", "OWNER_ID"], DIRECT_ADMIN_ID)

ADMIN_IDS: Set[int] = set()
for _part in RAW_ADMIN_IDS.replace(" ", ",").split(","):
    _part = _part.strip()
    if _part.isdigit():
        ADMIN_IDS.add(int(_part))

PORT = int(os.getenv("PORT", "10000"))

# ==================== LOGGING & DATABASE SETUP ====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("ForwardTagRemover")

DEFAULT_BOT_NAME = "Forward Tag Remover Pro"
BASE_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "forward_cleaner.db")
BD_TZ = timezone(timedelta(hours=6))

db_lock = threading.Lock()

http_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=40, pool_maxsize=40, max_retries=1)
http_session.mount("https://", _adapter)
http_session.mount("http://", _adapter)

# ==================== BUTTON CONSTANTS ====================
BTN_HOW_TO_USE = "📖 ব্যবহারের নিয়ম"
BTN_SETTINGS = "⚙️ ক্যাপশন সেটিংস"
BTN_LIVE_STATS = "📊 বট স্ট্যাটাস"
BTN_SUPPORT = "📞 হেল্প ও চ্যানেল"
BTN_ADMIN_PANEL = "👑 অ্যাডমিন প্যানেল"


# ==================== SQLITE3 DATABASE ====================
def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                caption_mode TEXT DEFAULT 'original', -- 'original', 'remove', 'custom'
                custom_caption TEXT DEFAULT '',
                is_banned INTEGER DEFAULT 0
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS stats (
                metric TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0
            )
            """
        )
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('bot_name', ?)", (DEFAULT_BOT_NAME,))
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('bot_username', '')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('force_sub', 'off')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('channel_username', '')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('support_username', '')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('maintenance', 'off')")

        for metric in ["messages_cleaned", "photos_cleaned", "videos_cleaned", "files_cleaned"]:
            c.execute("INSERT OR IGNORE INTO stats (metric, count) VALUES (?, 0)", (metric,))

        conn.commit()
        conn.close()


def get_setting(key: str, default: str = "") -> str:
    try:
        with db_lock:
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = c.fetchone()
            conn.close()
            return row["value"] if row else default
    except Exception:
        return default


def set_setting(key: str, value: str) -> None:
    try:
        with db_lock:
            conn = get_db()
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.error(f"Error setting {key}: {e}")


def increment_stat(metric: str, amount: int = 1) -> None:
    try:
        with db_lock:
            conn = get_db()
            c = conn.cursor()
            c.execute("UPDATE stats SET count = count + ? WHERE metric = ?", (amount, metric))
            conn.commit()
            conn.close()
    except Exception:
        pass


def get_stats() -> Dict[str, int]:
    try:
        with db_lock:
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) AS total_users FROM users")
            total_users = c.fetchone()["total_users"]
            c.execute("SELECT metric, count FROM stats")
            rows = c.fetchall()
            conn.close()
            res = {r["metric"]: r["count"] for r in rows}
            res["total_users"] = total_users
            return res
    except Exception:
        return {"total_users": 0, "messages_cleaned": 0, "photos_cleaned": 0, "videos_cleaned": 0, "files_cleaned": 0}


def get_user_config(user_id: int) -> Dict[str, str]:
    try:
        with db_lock:
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT caption_mode, custom_caption FROM users WHERE user_id = ?", (user_id,))
            row = c.fetchone()
            conn.close()
            if row:
                return {"caption_mode": row["caption_mode"] or "original", "custom_caption": row["custom_caption"] or ""}
    except Exception:
        pass
    return {"caption_mode": "original", "custom_caption": ""}


def set_user_config(user_id: int, mode: str, custom_caption: Optional[str] = None) -> None:
    try:
        with db_lock:
            conn = get_db()
            c = conn.cursor()
            if custom_caption is not None:
                c.execute("UPDATE users SET caption_mode = ?, custom_caption = ? WHERE user_id = ?", (mode, custom_caption, user_id))
            else:
                c.execute("UPDATE users SET caption_mode = ? WHERE user_id = ?", (mode, user_id))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.error(f"Error updating user config: {e}")


def register_user(user_id: int, username: str, first_name: str) -> None:
    try:
        with db_lock:
            conn = get_db()
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO users (user_id, username, first_name)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name
                """,
                (user_id, username, first_name),
            )
            conn.commit()
            conn.close()
    except Exception:
        pass


def is_user_banned(user_id: int) -> bool:
    try:
        with db_lock:
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
            row = c.fetchone()
            conn.close()
            return bool(row["is_banned"]) if row else False
    except Exception:
        return False


# ==================== TELEGRAM API REQUESTS ====================
def tg_request(method: str, data: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Dict[str, Any]:
    url = f"{BASE_API_URL}/{method}"
    try:
        resp = http_session.post(url, json=data or {}, timeout=timeout)
        return resp.json()
    except Exception as e:
        logger.error(f"Telegram API ({method}) error: {e}")
        return {"ok": False, "error": str(e)}


def sync_bot_info_from_telegram() -> None:
    try:
        tg_request("deleteWebhook", {"drop_pending_updates": True}, timeout=10)
        res = tg_request("getMe", timeout=10)
        if res.get("ok"):
            result = res.get("result") or {}
            tg_name = (result.get("first_name") or "").strip()
            tg_uname = (result.get("username") or "").strip()
            if tg_name:
                set_setting("bot_name", tg_name)
            if tg_uname:
                set_setting("bot_username", tg_uname)
    except Exception:
        pass


def send_message(chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None, parse_mode: str = "HTML") -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg_request("sendMessage", payload)


def edit_message_text(chat_id: int, message_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None, parse_mode: str = "HTML") -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg_request("editMessageText", payload)


def answer_callback_query(cb_id: str, text: Optional[str] = None, show_alert: bool = False) -> None:
    payload = {"callback_query_id": cb_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = show_alert
    tg_request("answerCallbackQuery", payload)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def safe_html(text: Any) -> str:
    if text is None:
        return ""
    return html.escape(str(text))


# ==================== FORCESUB VALIDATION ====================
def is_user_subscribed(user_id: int) -> bool:
    if is_admin(user_id):
        return True
    if get_setting("force_sub", "off").lower() != "on":
        return True
    ch = get_setting("channel_username", "").strip()
    if not ch:
        return True
    if not ch.startswith("@") and not ch.startswith("-100") and not ch.isdigit():
        ch = f"@{ch}"
    res = tg_request("getChatMember", {"chat_id": ch, "user_id": user_id})
    if res.get("ok"):
        status = (res.get("result") or {}).get("status", "")
        return status in ("creator", "administrator", "member", "restricted")
    return False


# ==================== FULL COLORED KEYBOARDS (TELEGRAM 9.4) ====================
def bottom_colorful_keyboard(user_id: int = 0) -> Dict[str, Any]:
    kb = [
        [
            {"text": BTN_HOW_TO_USE, "style": "primary"},
            {"text": BTN_SETTINGS, "style": "success"},
        ],
        [
            {"text": BTN_LIVE_STATS, "style": "primary"},
            {"text": BTN_SUPPORT, "style": "success"},
        ],
    ]
    if is_admin(user_id):
        kb.append([{"text": BTN_ADMIN_PANEL, "style": "danger"}])

    return {
        "keyboard": kb,
        "resize_keyboard": True,
        "is_persistent": True,
        "one_time_keyboard": False,
        "input_field_placeholder": "যেকোনো মেসেজ ফরোয়ার্ড করে পাঠান...",
    }


def settings_inline_keyboard(current_mode: str = "original") -> Dict[str, Any]:
    def _b_text(label: str, key: str) -> str:
        return f"{'✅ ' if current_mode == key else ''}{label}"

    return {
        "inline_keyboard": [
            [
                {
                    "text": _b_text("📄 আসল ক্যাপশন রাখুন", "original"),
                    "callback_data": "mode_original",
                    "style": "success" if current_mode == "original" else "primary",
                }
            ],
            [
                {
                    "text": _b_text("🗑️ ক্যাপশন সম্পূর্ণ মুছুন", "remove"),
                    "callback_data": "mode_remove",
                    "style": "success" if current_mode == "remove" else "primary",
                }
            ],
            [
                {
                    "text": _b_text("✍️ নিজের কাস্টম ক্যাপশন দিন", "custom"),
                    "callback_data": "mode_custom",
                    "style": "success" if current_mode == "custom" else "primary",
                }
            ],
        ]
    }


# ==================== USER STATE MANAGEMENT ====================
user_states: Dict[int, str] = {}


# ==================== HANDLERS ====================
def handle_start(user_id: int, username: str, first_name: str) -> None:
    register_user(user_id, username, first_name)
    if is_user_banned(user_id) and not is_admin(user_id):
        send_message(user_id, "🚫 আপনাকে এই বট ব্যবহার থেকে বিরত রাখা হয়েছে।")
        return

    bot_display = safe_html(get_setting("bot_name", DEFAULT_BOT_NAME))

    if not is_user_subscribed(user_id):
        ch = get_setting("channel_username", "").strip()
        ch_clean = ch.lstrip("@")
        ch_url = f"https://t.me/{ch_clean}" if ch_clean else "https://t.me"
        msg = (
            f"╭━━━⚠️ <b>চ্যানেল ভেরিফিকেশন আবশ্যক</b> ⚠️━━━╮\n"
            f"┃ প্রিয় <b>{safe_html(first_name)}</b>,\n"
            f"┃ <b>{bot_display}</b> ব্যবহার করতে আমাদের\n"
            f"┃ অফিশিয়াল চ্যানেলে জয়েন থাকুন।\n"
            f"╰━━━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
            f"👇 নিচের বাটনে চাপ দিয়ে জয়েন করে <b>'✅ জয়েন করেছি'</b> বাটনে চাপ দিন:"
        )
        kb = {
            "inline_keyboard": [
                [{"text": "📢 চ্যানেলে জয়েন করুন", "url": ch_url, "style": "primary"}],
                [{"text": "✅ জয়েন করেছি (Verify)", "callback_data": "check_sub", "style": "success"}],
            ]
        }
        send_message(user_id, msg, reply_markup=kb)
        return

    text = (
        f"╭━━━🧹 <b>{bot_display}</b> 🧹━━━╮\n"
        f"┃ 👤 <b>ইউজার:</b> {safe_html(first_name)}\n"
        f"┃ 🆔 <b>আইডি:</b> <code>{user_id}</code>\n"
        f"┃ ⚡ <b>স্পিড:</b> আল্ট্রা-ফাস্ট (১ সেকেন্ড)\n"
        f"╰━━━━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        "✨ <b>এই বটটি কী করতে পারে?</b>\n"
        "যে কোনো চ্যানেল বা গ্রুপ থেকে ছবি, ভিডিও, ফাইল, অডিও বা মেসেজ এই বটে ফরোয়ার্ড করলেই—\n"
        "বট মুহূর্তেই <b>'Forwarded from...' ট্যাগটি সম্পূর্ণ মুছে</b> একদম নতুন ফ্রেশ পোস্ট বানিয়ে দিয়ে দেবে! 🚀\n\n"
        "👇 <b>টেস্ট করতে যেকোনো একটি মেসেজ বা ফাইল এখনই এখানে ফরোয়ার্ড করুন!</b>"
    )
    send_message(user_id, text, reply_markup=bottom_colorful_keyboard(user_id))


def handle_how_to_use(user_id: int) -> None:
    text = (
        "╭━━━📖 <b>ব্যবহারের সহজ নিয়ম</b> ━━━╮\n"
        "১. যেকোনো চ্যানেল বা চ্যাট থেকে কোনো পোস্ট/ভিডিও/ছবি সিলেক্ট করুন।\n"
        "২. এই বটের ইনবক্সে সরাসরি <b>Forward</b> করে পাঠিয়ে দিন।\n"
        "৩. বট এক সেকেন্ডের মধ্যে 'Forwarded from' ট্যাগ সম্পূর্ণ মুছে একদম ফ্রেশ ফাইল হিসেবে রিটার্ন করবে!\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        "💡 <b>ক্যাপশন সেটিংস:</b>\n"
        "আপনি চাইলে আসল ক্যাপশন রাখতে পারেন, মুছে ফেলতে পারেন কিংবা নিজের চ্যানেলের লিংক কাস্টম ক্যাপশন হিসেবে সেট করে দিতে পারেন!"
    )
    send_message(user_id, text, reply_markup=bottom_colorful_keyboard(user_id))


def handle_settings_menu(user_id: int) -> None:
    cfg = get_user_config(user_id)
    mode = cfg["caption_mode"]
    c_cap = cfg["custom_caption"]

    mode_bangla = {
        "original": "📄 আসল ক্যাপশন থাকবে",
        "remove": "🗑️ ক্যাপশন সম্পূর্ণ মুছে ফেলা হবে",
        "custom": f"✍️ কাস্টম ক্যাপশন সেট করা:\n<code>{safe_html(c_cap[:80])}</code>",
    }.get(mode, "📄 আসল ক্যাপশন থাকবে")

    text = (
        "╭━━━⚙️ <b>ক্যাপশন সেটিংস কন্ট্রোল</b> ━━━╮\n"
        f"┃ 📌 <b>বর্তমান মোড:</b> {mode_bangla}\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        "👇 নিচের বাটন চাপ দিয়ে আপনার পছন্দমতো মোড বেছে নিন:"
    )
    send_message(user_id, text, reply_markup=settings_inline_keyboard(mode))


def resolve_caption_for_user(user_id: int, original_caption: Optional[str]) -> Optional[str]:
    cfg = get_user_config(user_id)
    mode = cfg["caption_mode"]
    if mode == "remove":
        return None
    elif mode == "custom":
        return cfg["custom_caption"] or original_caption
    return original_caption


def process_forward_media(msg: Dict[str, Any]) -> None:
    user_id = (msg.get("from") or {}).get("id")
    if not user_id:
        return

    # Extract caption
    orig_caption = msg.get("caption") or ""
    final_caption = resolve_caption_for_user(user_id, orig_caption if orig_caption else None)

    # 1. Text Message
    if "text" in msg and not any(k in msg for k in ["photo", "video", "document", "audio", "voice", "animation", "sticker"]):
        text_content = msg["text"]
        cfg = get_user_config(user_id)
        if cfg["caption_mode"] == "custom" and cfg["custom_caption"]:
            text_content = f"{text_content}\n\n{cfg['custom_caption']}"
        send_message(user_id, text_content)
        increment_stat("messages_cleaned", 1)
        return

    # 2. Photo
    if "photo" in msg:
        photos = msg["photo"]
        best_photo = photos[-1]["file_id"]
        payload: Dict[str, Any] = {"chat_id": user_id, "photo": best_photo}
        if final_caption:
            payload["caption"] = final_caption
            payload["parse_mode"] = "HTML"
        tg_request("sendPhoto", payload)
        increment_stat("photos_cleaned", 1)
        return

    # 3. Video
    if "video" in msg:
        vid_id = msg["video"]["file_id"]
        payload = {"chat_id": user_id, "video": vid_id}
        if final_caption:
            payload["caption"] = final_caption
            payload["parse_mode"] = "HTML"
        tg_request("sendVideo", payload)
        increment_stat("videos_cleaned", 1)
        return

    # 4. Document / File
    if "document" in msg:
        doc_id = msg["document"]["file_id"]
        payload = {"chat_id": user_id, "document": doc_id}
        if final_caption:
            payload["caption"] = final_caption
            payload["parse_mode"] = "HTML"
        tg_request("sendDocument", payload)
        increment_stat("files_cleaned", 1)
        return

    # 5. Audio
    if "audio" in msg:
        aud_id = msg["audio"]["file_id"]
        payload = {"chat_id": user_id, "audio": aud_id}
        if final_caption:
            payload["caption"] = final_caption
            payload["parse_mode"] = "HTML"
        tg_request("sendAudio", payload)
        increment_stat("files_cleaned", 1)
        return

    # 6. Voice
    if "voice" in msg:
        voc_id = msg["voice"]["file_id"]
        payload = {"chat_id": user_id, "voice": voc_id}
        if final_caption:
            payload["caption"] = final_caption
            payload["parse_mode"] = "HTML"
        tg_request("sendVoice", payload)
        increment_stat("files_cleaned", 1)
        return

    # 7. Animation / GIF
    if "animation" in msg:
        anim_id = msg["animation"]["file_id"]
        payload = {"chat_id": user_id, "animation": anim_id}
        if final_caption:
            payload["caption"] = final_caption
            payload["parse_mode"] = "HTML"
        tg_request("sendAnimation", payload)
        increment_stat("files_cleaned", 1)
        return

    # 8. Sticker
    if "sticker" in msg:
        stk_id = msg["sticker"]["file_id"]
        tg_request("sendSticker", {"chat_id": user_id, "sticker": stk_id})
        increment_stat("messages_cleaned", 1)
        return


def handle_live_stats(user_id: int) -> None:
    stats = get_stats()
    bot_display = safe_html(get_setting("bot_name", DEFAULT_BOT_NAME))
    text = (
        f"╭━━━📊 <b>{bot_display} — স্ট্যাটাস</b> 📊━━━╮\n"
        f"┃ 👥 <b>মোট ইউজার:</b> <code>{stats['total_users']}</code> জন\n"
        f"┃ 🧹 <b>মোট ক্লিন মেসেজ:</b> <code>{stats['messages_cleaned']}</code> টি\n"
        f"┃ 🖼️ <b>মোট ক্লিন ছবি:</b> <code>{stats['photos_cleaned']}</code> টি\n"
        f"┃ 🎬 <b>মোট ক্লিন ভিডিও:</b> <code>{stats['videos_cleaned']}</code> টি\n"
        f"┃ 📁 <b>মোট ক্লিন ফাইল:</b> <code>{stats['files_cleaned']}</code> টি\n"
        f"┃ ⚡ <b>সার্ভার স্পিড:</b> ১ সেকেন্ড (আল্ট্রা ফাস্ট)\n"
        f"╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯"
    )
    send_message(user_id, text, reply_markup=bottom_colorful_keyboard(user_id))


def handle_support(user_id: int) -> None:
    ch = get_setting("channel_username", "").strip().replace("https://t.me/", "").lstrip("@")
    sup = get_setting("support_username", "").strip().replace("https://t.me/", "").lstrip("@")
    bot_display = safe_html(get_setting("bot_name", DEFAULT_BOT_NAME))

    lines = [
        f"╭━━━📞 <b>{bot_display} — হেল্প সেন্টার</b> 📞━━━╮",
        "┃ যেকোনো চ্যানেল বা চ্যাট থেকে মেসেজ/ফাইল",
        "┃ এখানে ফরোয়ার্ড করলেই 'Forwarded from' ট্যাগ",
        "┃ মুছে দিয়ে ফ্রেশ কপি পাঠিয়ে দেওয়া হবে।",
        "╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯",
        "",
        f"📢 <b>অফিশিয়াল চ্যানেল:</b> {'@' + ch if ch else 'সেট করা নেই'}",
        f"👨‍💻 <b>হেল্প ও সাপোর্ট:</b> {'@' + sup if sup else 'সেট করা নেই'}",
    ]
    kb_rows = []
    if ch:
        kb_rows.append([{"text": "📢 অফিশিয়াল চ্যানেল", "url": f"https://t.me/{ch}", "style": "primary"}])
    if sup:
        kb_rows.append([{"text": "👨‍💻 হেল্প ও সাপোর্ট", "url": f"https://t.me/{sup}", "style": "success"}])

    kb = {"inline_keyboard": kb_rows} if kb_rows else None
    send_message(user_id, "\n".join(lines), reply_markup=kb)


# ==================== ADMIN PANEL ====================
def build_admin_panel_text() -> str:
    stats = get_stats()
    fs_status = get_setting("force_sub", "off").upper()
    ch = get_setting("channel_username", "")
    ch_display = f"@{ch.lstrip('@')}" if ch else "সেট করা নেই"
    sup = get_setting("support_username", "")
    sup_display = f"@{sup.lstrip('@')}" if sup else "সেট করা নেই"

    return (
        "╭━━━👑 <b>অ্যাডমিন কন্ট্রোল প্যানেল</b> 👑━━━╮\n"
        f"┃ 👥 <b>মোট ইউজার:</b> <code>{stats['total_users']}</code> জন\n"
        f"┃ 🧹 <b>মোট ক্লিন মিডিয়া:</b> <code>{stats['messages_cleaned'] + stats['photos_cleaned'] + stats['videos_cleaned'] + stats['files_cleaned']}</code> টি\n"
        f"┃ 🔒 <b>ফোর্স সাবস্ক্রিপশন:</b> <code>{fs_status}</code>\n"
        f"┃ 📢 <b>বর্তমান চ্যানেল:</b> <code>{safe_html(ch_display)}</code>\n"
        f"┃ 👨‍💻 <b>সাপোর্ট আইডি:</b> <code>{safe_html(sup_display)}</code>\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        "👇 নিচের বাটন দিয়ে সেটিংস পরিবর্তন করুন:"
    )


def admin_inline_keyboard() -> Dict[str, Any]:
    fs = get_setting("force_sub", "off").lower()
    fs_label = "🔒 Force-Sub: [ON]" if fs == "on" else "🔓 Force-Sub: [OFF]"

    return {
        "inline_keyboard": [
            [{"text": "📢 ব্রডকাস্ট মেসেজ পাঠান", "callback_data": "admin_broadcast", "style": "primary"}],
            [
                {"text": fs_label, "callback_data": "admin_toggle_forcesub", "style": "success" if fs == "on" else "danger"},
                {"text": "📢 চ্যানেল সেট করুন", "callback_data": "admin_set_channel", "style": "primary"},
            ],
            [{"text": "👨‍💻 সাপোর্ট আইডি সেট করুন", "callback_data": "admin_set_support", "style": "primary"}],
            [{"text": "🔄 রিফ্রেশ প্যানেল", "callback_data": "admin_refresh", "style": "success"}],
        ]
    }


def handle_admin_panel(user_id: int, edit_msg_id: Optional[int] = None) -> None:
    text = build_admin_panel_text()
    kb = admin_inline_keyboard()
    if edit_msg_id:
        edit_message_text(user_id, edit_msg_id, text, reply_markup=kb)
    else:
        send_message(user_id, text, reply_markup=kb)


# ==================== MESSAGE & CALLBACK ROUTING ====================
def process_message(msg: Dict[str, Any]) -> None:
    user_id = (msg.get("from") or {}).get("id")
    if not user_id:
        return

    text = (msg.get("text") or "").strip()
    username = (msg.get("from") or {}).get("username") or ""
    first_name = (msg.get("from") or {}).get("first_name") or "User"
    register_user(user_id, username, first_name)

    if is_user_banned(user_id) and not is_admin(user_id):
        return

    # Check waiting states
    if user_id in user_states:
        state = user_states[user_id]
        if text.lower() in ("বাতিল", "cancel"):
            user_states.pop(user_id, None)
            send_message(user_id, "❌ অপারেশন বাতিল করা হয়েছে।", reply_markup=bottom_colorful_keyboard(user_id))
            return

        if state == "waiting_custom_caption":
            user_states.pop(user_id, None)
            set_user_config(user_id, mode="custom", custom_caption=text)
            send_message(user_id, f"✅ আপনার কাস্টম ক্যাপশন সেট করা হয়েছে:\n\n<code>{safe_html(text)}</code>", reply_markup=bottom_colorful_keyboard(user_id))
            return

        if state == "waiting_broadcast" and is_admin(user_id):
            user_states.pop(user_id, None)
            send_message(user_id, "⏳ ব্রডকাস্ট পাঠানো শুরু হয়েছে...")
            count = 0
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT user_id FROM users WHERE is_banned = 0")
                rows = c.fetchall()
                conn.close()
            for r in rows:
                target_uid = r["user_id"]
                res = send_message(target_uid, f"📢 <b>অ্যাডমিন বার্তা:</b>\n\n{safe_html(text)}")
                if res.get("ok"):
                    count += 1
                time.sleep(0.04)
            send_message(user_id, f"✅ ব্রডকাস্ট সম্পন্ন! মোট <code>{count}</code> জন ইউজারের কাছে পাঠানো হয়েছে।")
            return

        if state == "waiting_set_channel" and is_admin(user_id):
            user_states.pop(user_id, None)
            clean_ch = text.strip().replace("https://t.me/", "").lstrip("@")
            set_setting("channel_username", clean_ch)
            set_setting("force_sub", "on")
            send_message(user_id, f"✅ চ্যানেল সফলভাবে <b>@{clean_ch}</b> সেট হয়েছে এবং Force-Sub [ON] করা হয়েছে!")
            handle_admin_panel(user_id)
            return

        if state == "waiting_set_support" and is_admin(user_id):
            user_states.pop(user_id, None)
            clean_sup = text.strip().replace("https://t.me/", "").lstrip("@")
            set_setting("support_username", clean_sup)
            send_message(user_id, f"✅ সাপোর্ট আইডি সফলভাবে <b>@{clean_sup}</b> সেট করা হয়েছে!")
            handle_admin_panel(user_id)
            return

    # Check commands & bottom buttons
    if text == "/start":
        handle_start(user_id, username, first_name)
    elif text in (BTN_HOW_TO_USE, "/help"):
        handle_how_to_use(user_id)
    elif text in (BTN_SETTINGS, "/settings"):
        handle_settings_menu(user_id)
    elif text in (BTN_LIVE_STATS, "/stats"):
        handle_live_stats(user_id)
    elif text in (BTN_SUPPORT, "/support"):
        handle_support(user_id)
    elif text in (BTN_ADMIN_PANEL, "/admin") and is_admin(user_id):
        handle_admin_panel(user_id)
    else:
        # Any other message / forwarded media -> CLEAN FORWARD TAG
        process_forward_media(msg)


def process_callback_query(cb: Dict[str, Any]) -> None:
    cb_id = cb.get("id")
    from_user = cb.get("from") or {}
    user_id = from_user.get("id")
    data = cb.get("data", "")
    msg = cb.get("message") or {}
    msg_id = msg.get("message_id")

    if not user_id or not cb_id:
        return

    if data == "check_sub":
        if is_user_subscribed(user_id):
            answer_callback_query(cb_id, "✅ ভেরিফিকেশন সফল হয়েছে!", show_alert=True)
            handle_start(user_id, from_user.get("username", ""), from_user.get("first_name", "User"))
        else:
            answer_callback_query(cb_id, "❌ আপনি এখনো চ্যানেলে জয়েন করেননি! আগে জয়েন করে আবার চেষ্টা করুন।", show_alert=True)
        return

    answer_callback_query(cb_id)

    # Caption mode settings
    if data == "mode_original":
        set_user_config(user_id, mode="original")
        send_message(user_id, "✅ এখন থেকে ফরোয়ার্ড করা মিডিয়ার <b>আসল ক্যাপশন</b> অক্ষুণ্ণ থাকবে।", reply_markup=bottom_colorful_keyboard(user_id))
        return

    if data == "mode_remove":
        set_user_config(user_id, mode="remove")
        send_message(user_id, "✅ এখন থেকে সব ক্যাপশন মুছে দিয়ে <b>একদম ফ্রেশ মিডিয়া</b> দেওয়া হবে।", reply_markup=bottom_colorful_keyboard(user_id))
        return

    if data == "mode_custom":
        user_states[user_id] = "waiting_custom_caption"
        send_message(user_id, "✍️ <b>আপনার কাস্টম ক্যাপশন লিখে পাঠান</b> (যেমন: আপনার চ্যানেলের লিংক বা টেক্সট):", reply_markup=bottom_colorful_keyboard(user_id))
        return

    # Admin Panel Callbacks
    if data.startswith("admin_") and is_admin(user_id):
        if data == "admin_refresh":
            handle_admin_panel(user_id, edit_msg_id=msg_id)
        elif data == "admin_broadcast":
            user_states[user_id] = "waiting_broadcast"
            send_message(user_id, "📢 <b>সব ইউজারের কাছে যে মেসেজ পাঠাতে চান তা লিখে পাঠান</b> (অথবা <code>বাতিল</code> লিখুন):")
        elif data == "admin_toggle_forcesub":
            ch = get_setting("channel_username", "").strip()
            curr = get_setting("force_sub", "off").lower()
            if curr == "off" and not ch:
                user_states[user_id] = "waiting_set_channel"
                send_message(user_id, "📢 <b>চ্যানেল ইউজারনেম লিখে পাঠান</b> (যেমন: <code>TonmoyDeveloperBD24</code>):")
            else:
                new_st = "off" if curr == "on" else "on"
                set_setting("force_sub", new_st)
                handle_admin_panel(user_id, edit_msg_id=msg_id)
        elif data == "admin_set_channel":
            user_states[user_id] = "waiting_set_channel"
            send_message(user_id, "📢 <b>নতুন চ্যানেল ইউজারনেম লিখে পাঠান</b> (যেমন: <code>TonmoyDeveloperBD24</code>):")
        elif data == "admin_set_support":
            user_states[user_id] = "waiting_set_support"
            send_message(user_id, "👨‍💻 <b>নতুন সাপোর্ট ইউজারনেম লিখে পাঠান</b> (যেমন: <code>YourUsername</code>):")


# ==================== RENDER 24/7 HEALTH SERVER ====================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        stats = get_stats()
        b_name = get_setting("bot_name", DEFAULT_BOT_NAME)
        payload = {
            "status": "online",
            "bot": b_name,
            "total_users": stats["total_users"],
            "messages_cleaned": stats["messages_cleaned"],
            "photos_cleaned": stats["photos_cleaned"],
            "videos_cleaned": stats["videos_cleaned"],
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        pass


def run_http_server() -> None:
    server = HTTPServer(("0.0.0.0", PORT), HealthCheckHandler)
    logger.info(f"🌐 24/7 Render HTTP Keep-Alive Server running on port {PORT}")
    server.serve_forever()


# ==================== MAIN LOOP ====================
def main() -> None:
    init_db()
    threading.Thread(target=run_http_server, daemon=True).start()

    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN is missing! Set DIRECT_BOT_TOKEN in code or BOT_TOKEN in Environment Variables.")
        while True:
            time.sleep(10)

    sync_bot_info_from_telegram()
    logger.info(f"🚀 Forward Tag Remover Pro is online and polling...")
    offset = 0

    while True:
        try:
            resp = tg_request(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 25,
                    "allowed_updates": ["message", "callback_query"],
                },
                timeout=30,
            )
            if resp.get("ok"):
                for u in resp.get("result", []):
                    offset = u.get("update_id", offset) + 1
                    if "message" in u:
                        threading.Thread(
                            target=process_message,
                            args=(u["message"],),
                            daemon=True,
                        ).start()
                    elif "callback_query" in u:
                        threading.Thread(
                            target=process_callback_query,
                            args=(u["callback_query"],),
                            daemon=True,
                        ).start()
            else:
                time.sleep(2)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(3)


if __name__ == "__main__":
    main()