import asyncio
import os
import sqlite3
import random
import threading
import re
import time
from datetime import datetime

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.network.connection.tcpabridged import ConnectionTcpAbridged
from http.server import BaseHTTPRequestHandler, HTTPServer

# ========================= CONFIG =========================
API_ID = 35975193
API_HASH = '5929ba2233799d47756cfee57b71c4a5'

SESSION_STR = os.getenv("TELEGRAM_SESSION")
REPORT_CHAT_ID = 8748575384

# ====================== LOG ======================
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ====================== DB ======================
def db():
    return sqlite3.connect("db.sqlite3", check_same_thread=False)

def init_db():
    conn = db()
    conn.execute("CREATE TABLE IF NOT EXISTS leads (user_id INTEGER PRIMARY KEY, status TEXT)")
    conn.close()

# ====================== HANDLER ======================
client = None

def register_handlers(client):

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        try:
            uid = event.sender_id
            chat = await event.get_chat()
            title = getattr(chat, 'title', 'PRIVATE')
            text = event.raw_text or ""

            log(f"📩 {title} | {uid} | {text}")

            if not event.is_group:
                return

            if "тест" not in text.lower():
                return

            log("🎯 TEST FOUND")

            await client.send_message(
                REPORT_CHAT_ID,
                f"✅ Поймал:\n{text}"
            )

        except Exception as e:
            log(f"❌ handler error: {e}")

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

# ====================== CONNECT LOOP ======================
async def start_bot():
    global client

    while True:
        try:
            log("🔌 Connecting to Telegram...")

            client = TelegramClient(
                StringSession(SESSION_STR),
                API_ID,
                API_HASH,
                connection=ConnectionTcpAbridged,
                timeout=30,
                request_retries=5,
                connection_retries=999999,
                retry_delay=5,
                auto_reconnect=True
            )

            register_handlers(client)

            await client.start()

            me = await client.get_me()
            log(f"🚀 Started as {me.first_name}")

            # уведомление о запуске
            try:
                await client.send_message(
                    REPORT_CHAT_ID,
                    f"🟢 Бот запущен\n{me.first_name}\n{datetime.now().strftime('%H:%M:%S')}"
                )
            except Exception as e:
                log(f"❌ notify error: {e}")

            # прогрев
            await client.get_dialogs()

            log("✅ Listening...")

            await client.run_until_disconnected()

        except Exception as e:
            log(f"❌ CONNECTION ERROR: {e}")
            log("🔄 Retry in 5 sec...")
            await asyncio.sleep(5)

# ====================== MAIN ======================
def main():
    init_db()
    threading.Thread(target=health, daemon=True).start()
    asyncio.run(start_bot())

if __name__ == "__main__":
    main()
