import asyncio
import os
import sqlite3
import random
import threading
import re
import time
from datetime import datetime, timezone

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from openai import AsyncOpenAI
from http.server import BaseHTTPRequestHandler, HTTPServer

# ========================= КОНФИГ =========================
API_ID = 35975193
API_HASH = '5929ba2233799d47756cfee57b71c4a5'

REPORT_CHAT_ID = 8748575384
RECRUITER_TAG = "@HRpolsha"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SESSION_STR = os.getenv("TELEGRAM_SESSION")

ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
DB_PATH = "leads_v3.db"

TRIGGER_WORDS = ["тест", "test", "ищу работу", "ищу жилье"]
STOP_WORDS = ["вакансия", "набираем"]

MAX_MESSAGES_PER_HOUR = 15
sent_times = []

# ====================== LOG ======================
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ====================== DB ======================
def db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = db()
    conn.execute('CREATE TABLE IF NOT EXISTS leads (user_id INTEGER PRIMARY KEY, status TEXT)')
    conn.close()

def get_status(user_id):
    conn = db()
    row = conn.execute("SELECT status FROM leads WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row[0] if row else None

def set_status(user_id, status):
    conn = db()
    conn.execute("INSERT OR REPLACE INTO leads (user_id, status) VALUES (?, ?)", (user_id, status))
    conn.commit()
    conn.close()

# ====================== АНТИ-ФЛУД ======================
def can_send():
    now = time.time()
    global sent_times

    sent_times = [t for t in sent_times if now - t < 3600]

    if len(sent_times) >= MAX_MESSAGES_PER_HOUR:
        return False

    sent_times.append(now)
    return True

# ====================== PHONE ======================
def extract_phone(text):
    match = re.search(r'(\+?\d[\d\-\s]{8,15}\d)', text)
    return match.group(0) if match else "нет"

# ====================== AI ======================
async def ai_check(text):
    if not ai_client.api_key:
        log("⚠️ AI выключен")
        return True

    try:
        res = await ai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "Ответь ДА или НЕТ"},
                {"role": "user", "content": text}
            ],
            max_tokens=5
        )
        answer = res.choices[0].message.content.upper()
        log(f"🧠 AI ответ: {answer}")
        return "ДА" in answer
    except Exception as e:
        log(f"❌ AI ошибка: {e}")
        return False

# ====================== CLIENT ======================
init_db()

client = TelegramClient(
    StringSession(SESSION_STR),
    API_ID,
    API_HASH,
    device_model="iPhone 13",
    system_version="16.0",
    app_version="9.0"
)

# ====================== HANDLER ======================
@client.on(events.NewMessage(incoming=True))
async def handler(event):
    try:
        uid = event.sender_id

        chat = await event.get_chat()
        chat_title = getattr(chat, 'title', 'PRIVATE')

        text = event.raw_text or ""

        log(f"📩 MSG | chat: {chat_title} | user: {uid}")
        log(f"💬 TEXT: {text}")

        if not uid:
            log("⛔ нет uid")
            return

        sender = await event.get_sender()

        if getattr(sender, 'bot', False):
            log("🤖 skip bot")
            return

        if not event.is_group:
            log("⏭️ skip private")
            return

        text_lower = text.lower()

        # стоп-слова
        if any(sw in text_lower for sw in STOP_WORDS):
            log("⛔ стоп-слово")
            return

        # триггер
        trigger = next((w for w in TRIGGER_WORDS if w in text_lower), None)

        if not trigger:
            log("⏭️ нет триггера")
            return

        log(f"🎯 TRIGGER: {trigger}")

        # дубль
        if get_status(uid):
            log("🔁 уже есть в базе")
            return

        set_status(uid, "processing")

        # AI
        if not await ai_check(text):
            log("❌ AI отказ")
            set_status(uid, "rejected")
            return

        username = f"@{sender.username}" if sender.username else None

        if not username:
            log("⛔ нет username")
            set_status(uid, "no_username")
            return

        # отчёт
        report = (
            f"🎯 ЛИД\n"
            f"{RECRUITER_TAG}\n\n"
            f"👤 {sender.first_name}\n"
            f"🆔 {uid}\n"
            f"🔗 {username}\n"
            f"📞 {extract_phone(text)}\n"
            f"🏠 {chat_title}\n\n"
            f"{text[:200]}"
        )

        log("📤 отправка отчёта...")
        await client.send_message(REPORT_CHAT_ID, report)

        set_status(uid, "sent")

        # антифлуд
        if not can_send():
            log("⛔ flood limit")
            return

        await asyncio.sleep(30)

        await client.send_message(uid, "Здравствуйте! Актуально еще?")

        log("💌 отправлено ЛС")

    except Exception as e:
        log(f"❌ ERROR: {e}")

# ====================== HEALTH ======================
def health():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(
        ('0.0.0.0', port),
        type('H', (BaseHTTPRequestHandler,), {
            'do_GET': lambda s: (
                s.send_response(200),
                s.end_headers(),
                s.wfile.write(b"OK")
            )
        })
    )
    server.serve_forever()

# ====================== MAIN ======================
async def main():
    threading.Thread(target=health, daemon=True).start()

    log("🔌 Connecting...")
    await client.start()

    me = await client.get_me()
    log(f"🚀 Started: {me.first_name}")

    log("📡 Загружаю диалоги...")
    dialogs = await client.get_dialogs()

    for d in dialogs[:20]:
        log(f"👉 Диалог: {d.name}")

    log("✅ Готов слушать сообщения...")

    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
