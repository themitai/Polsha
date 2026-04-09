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

# ========================= КОНФИГУРАЦИЯ =========================
API_ID = 35975193
API_HASH = '5929ba2233799d47756cfee57b71c4a5'

REPORT_CHAT_ID = 8748575384
RECRUITER_TAG = "@HRpolsha"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SESSION_STR = os.getenv("TELEGRAM_SESSION")

ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
DB_PATH = "leads_v3.db"

MAX_MESSAGES_PER_HOUR = 15

TRIGGER_WORDS = [
    "пеший переход", "приехал сегодня", "очередь на границе", "еду в польшу", "выезжаю из",
    "карта побыту", "мельдунок", "pesel", "подача на карту", "виза закончилась",
    "ищу жилье", "сниму квартиру", "нужна комната", "ищу кавалерку",
    "ищу работу", "шукаю роботу", "подработка", "підробіток",
    "детский сад", "садик", "школа для ребенка", "800+", "dobry start",
    "тест", "test"
]

STOP_WORDS = [
    "ищем", "требуется", "вакансия", "набираем", "предлагаем",
    "услуги", "помогу", "работа для", "заработок", "приглашаем",
    "оформление", "официально"
]

# ====================== ЛОГ ======================
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ====================== PHONE ======================
def extract_phone(text):
    pattern = r'(\+?\d[\d\-\s]{8,15}\d)'
    match = re.search(pattern, text)
    return match.group(0) if match else "Не указан"

# ====================== БАЗА ======================
def db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = db()
    conn.execute('CREATE TABLE IF NOT EXISTS leads (user_id INTEGER PRIMARY KEY, status TEXT, category TEXT)')
    conn.close()

def get_status(user_id):
    try:
        conn = db()
        row = conn.execute("SELECT status FROM leads WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        log(f"❌ DB get_status: {e}")
        return None

def set_status(user_id, status, category="unknown"):
    try:
        conn = db()
        conn.execute(
            "INSERT OR REPLACE INTO leads (user_id, status, category) VALUES (?, ?, ?)",
            (user_id, status, category)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log(f"❌ DB set_status: {e}")

# ====================== АНТИ-ФЛУД ======================
sent_times = []

def can_send():
    now = time.time()
    global sent_times

    sent_times = [t for t in sent_times if now - t < 3600]

    if len(sent_times) >= MAX_MESSAGES_PER_HOUR:
        return False

    sent_times.append(now)
    return True

# ====================== ИИ ======================
async def ai_check(text):
    if not ai_client.api_key:
        return True

    try:
        prompt = "Ответь ТОЛЬКО 'ДА' или 'НЕТ'. 'ДА' — если человек ищет помощь/жилье/работу. 'НЕТ' — если реклама."

        res = await ai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text}
            ],
            max_tokens=5,
            temperature=0
        )

        answer = res.choices[0].message.content.strip().upper()
        log(f"🧠 AI: {answer}")
        return "ДА" in answer

    except Exception as e:
        log(f"❌ AI error: {e}")
        return False

# ====================== ОБРАБОТЧИК ======================
init_db()
client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    uid = event.sender_id
    if not uid:
        return

    sender = await event.get_sender()
    if getattr(sender, 'bot', False):
        return

    if not event.is_group:
        return

    chat = await event.get_chat()

    msg_age = (datetime.now(timezone.utc) - event.date).total_seconds()
    if msg_age > 600:
        return

    text = event.raw_text
    text_lower = text.lower()

    if any(sw in text_lower for sw in STOP_WORDS):
        return

    trigger = next((w for w in TRIGGER_WORDS if w in text_lower), None)
    if not trigger:
        return

    if get_status(uid):
        return

    set_status(uid, "processing")

    log(f"🎯 HIT: {uid}")

    if not await ai_check(text):
        set_status(uid, "rejected")
        return

    try:
        username = f"@{sender.username}" if sender.username else None

        if not username:
            set_status(uid, "no_username")
            return

        phone_in_text = extract_phone(text)
        user_phone = getattr(sender, 'phone', 'hidden')
        user_link = f"tg://user?id={uid}"

        report = (
            f"🎯 **НОВЫЙ ЛИД**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{RECRUITER_TAG}\n\n"
            f"👤 Имя: {sender.first_name or '—'} {sender.last_name or ''}\n"
            f"🆔 ID: `{uid}`\n"
            f"🔗 Username: {username}\n"
            f"📱 Телефон (профиль): `{user_phone}`\n"
            f"📞 Телефон (текст): `{phone_in_text}`\n"
            f"🏠 Группа: {chat.title if hasattr(chat, 'title') else '—'}\n"
            f"🔗 Ссылка: tg://user?id={uid}\n\n"
            f"💬 Сообщение:\n_{text[:300]}_\n\n"
            f"🔍 Триггер: #{trigger.replace(' ', '_')}"
        )

        await client.send_message(REPORT_CHAT_ID, report, link_preview=False)

        set_status(uid, "sent")

        if not can_send():
            log("⛔ Flood limit")
            return

        await asyncio.sleep(random.randint(60, 180))

        if random.random() < 0.5:
            log("⏭️ Skip DM (random)")
            return

        await client.send_message(uid, "Здравствуйте! Увидела ваш пост. Актуально еще?")

        log(f"💌 Sent DM: {uid}")

    except Exception as e:
        log(f"❌ ERROR: {e}")
        set_status(uid, "error")

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

    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
