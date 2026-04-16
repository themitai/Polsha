import asyncio
import os
import sqlite3
import random
import threading
from datetime import datetime, timezone

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError, UserIsBlockedError
from openai import AsyncOpenAI
from http.server import BaseHTTPRequestHandler, HTTPServer

# ========================= БАЗОВЫЕ ДАННЫЕ =========================
API_ID = 38165468
API_HASH = '387dc50469f115c50fc7a4f36a9b84b3'
REPORT_CHAT_ID = 8348598832
RECRUITER_TAG = "@botlooklead"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

DB_PATH = "leads_v3.db"

# ====================== ЗАГРУЗКА ДО 6 СЕССИЙ ======================
ACCOUNTS = {}
for i in range(1, 7):  # от 1 до 6
    session = os.getenv(f"TELEGRAM_SESSION{i}")
    if session:
        ACCOUNTS[f"account{i}"] = session

if not ACCOUNTS:
    print("❌ Ошибка: Не найдено ни одной сессии (TELEGRAM_SESSION1 ... TELEGRAM_SESSION6)")
    exit(1)

print(f"✅ Загружено аккаунтов: {len(ACCOUNTS)}")

# ====================== ТРИГГЕРЫ ======================
TRIGGER_WORDS = [
    "пеший переход", "приехал сегодня", "очередь на границе", "еду в польшу", "выезжаю из",
    "карта побыту", "мельдунок", "pesel", "подача на карту", "виза закончилась",
    "ищу жилье", "сниму квартиру", "нужна комната", "ищу кавалерку",
    "ищу работу", "шукаю роботу", "подработка", "підробіток",
    "детский сад", "садик", "школа для ребенка", "800+", "dobry start"
]

STOP_WORDS = ["ищем", "требуется", "вакансия", "набираем", "предлагаем", "услуги", "помогу"]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ====================== БАЗА ======================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('CREATE TABLE IF NOT EXISTS leads (user_id INTEGER PRIMARY KEY, status TEXT, category TEXT, account TEXT)')
    conn.close()

def get_status(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT status FROM leads WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        return row[0] if row else None
    except:
        return None

def set_status(user_id, status, category="unknown", account="unknown"):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR REPLACE INTO leads (user_id, status, category, account) VALUES (?, ?, ?, ?)",
                     (user_id, status, category, account))
        conn.commit()
        conn.close()
    except:
        pass

# ====================== ИИ ======================
async def ai_check(text, mode="is_lead"):
    if not ai_client:
        return True
    try:
        prompt = "Ответь ТОЛЬКО ДА или НЕТ. ДА — если человек ищет помощь (жильё, работа, документы, переезд и т.д.)."
        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": text}],
            max_tokens=5,
            temperature=0
        )
        answer = res.choices[0].message.content.strip().upper()
        return "ДА" in answer
    except:
        return False

# ====================== ЗАПУСК ОДНОГО АККАУНТА ======================
async def start_account(account_name, session_str):
    if not session_str:
        return

    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)

    @client.on(events.NewMessage)
    async def handler(event):
        if not event.is_group or not event.sender_id:
            return

        text_lower = event.raw_text.lower()

        if any(word in text_lower for word in STOP_WORDS):
            return

        if any(word in text_lower for word in TRIGGER_WORDS):
            if get_status(event.sender_id) is None:
                if await ai_check(event.raw_text, "is_lead"):
                    try:
                        chat = await event.get_chat()
                        user_link = f"tg://user?id={event.sender_id}"

                        report = (
                            f"🎯 **ЛИД НАЙДЕН** | {account_name.upper()}\n"
                            f"👤 {event.sender.first_name or '—'}\n"
                            f"🆔 `{event.sender_id}`\n"
                            f"🔗 [Профиль]({user_link})\n"
                            f"🏠 Группа: {chat.title}\n"
                            f"💬 {event.raw_text[:180]}"
                        )

                        await client.send_message(REPORT_CHAT_ID, report, link_preview=False)
                        log(f"✅ Лид найден с аккаунта {account_name}")
                    except Exception as e:
                        log(f"Ошибка отправки отчёта с {account_name}: {e}")

    await client.start()
    me = await client.get_me()
    log(f"✅ Аккаунт {account_name} запущен → {me.first_name} (@{me.username or '—'})")

    await client.run_until_disconnected()

# ====================== MAIN ======================
async def main():
    def health():
        port = int(os.getenv("PORT", 8080))
        server = HTTPServer(('0.0.0.0', port),
            type('H', (BaseHTTPRequestHandler,), {'do_GET': lambda s: (s.send_response(200), s.end_headers(), s.wfile.write(b"OK"))}))
        server.serve_forever()
    threading.Thread(target=health, daemon=True).start()

    log("🚀 Запуск Multi-Account Lead Generator (до 6 аккаунтов)...")

    tasks = []
    for name, session in ACCOUNTS.items():
        if session:
            tasks.append(start_account(name, session))

    if tasks:
        await asyncio.gather(*tasks)
    else:
        log("❌ Нет активных сессий для запуска!")

if __name__ == '__main__':
    asyncio.run(main())
