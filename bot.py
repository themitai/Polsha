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

# ========================= CONFIG =========================
API_ID = 35975193
API_HASH = '5929ba2233799d47756cfee57b71c4a5'

REPORT_CHAT_ID = 8748575384
RECRUITER_TAG = "@HRpolsha"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SESSION_STR = os.getenv("TELEGRAM_SESSION")

ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
DB_PATH = "leads_v3.db"

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

# ====================== HANDLER ======================
@client.on(events.NewMessage(incoming=True))
async def handler(event):
    try:
        uid = event.sender_id
        chat = await event.get_chat()
        chat_title = getattr(chat, 'title', 'PRIVATE')
        text = event.raw_text or ""

        log(f"📩 MSG | {chat_title} | {uid}")

        if not event.is_group:
            return

        if not text:
            return

        if "тест" not in text.lower():
            return

        log("🎯 FOUND TEST MESSAGE")

        await client.send_message(REPORT_CHAT_ID, f"✅ Поймал сообщение:\n{text}")

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
async def run_bot():
    global client

    while True:
        try:
            log("🔌 Connecting...")

            client = TelegramClient(
                StringSession(SESSION_STR),
                API_ID,
                API_HASH,
                device_model="iPhone 13",
                system_version="16.0",
                app_version="9.0",
                connection_retries=None  # бесконечные попытки
            )

            await client.start()

            me = await client.get_me()
            log(f"🚀 Started: {me.first_name}")

            # 🔔 УВЕДОМЛЕНИЕ О ЗАПУСКЕ
            try:
                await client.send_message(
                    REPORT_CHAT_ID,
                    f"🟢 Бот запущен\n👤 {me.first_name}\n⏰ {datetime.now().strftime('%H:%M:%S')}"
                )
            except Exception as e:
                log(f"❌ Не смог отправить старт сообщение: {e}")

            # прогрев
            dialogs = await client.get_dialogs()
            for d in dialogs[:10]:
                log(f"👉 {d.name}")

            log("✅ Listening...")

            await client.run_until_disconnected()

        except Exception as e:
            log(f"❌ CONNECTION LOST: {e}")
            log("🔄 Переподключение через 5 сек...")
            await asyncio.sleep(5)

# ====================== START ======================
init_db()

def main():
    threading.Thread(target=health, daemon=True).start()
    asyncio.run(run_bot())

if __name__ == "__main__":
    main()
