import asyncio
import os
import sqlite3
import random
from datetime import datetime, timezone
from telethon import TelegramClient, events
from openai import AsyncOpenAI
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- [КОНФИГУРАЦИЯ] ---
API_ID = 35523804
API_HASH = 'ff7673ebc0e925a32fb52693bdfae16f'
REPORT_CHAT_ID = 7238685565
RECRUITER_TAG = "@hannaober"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# Путь к базе и сессии на постоянном диске Railway
DB_PATH = '/app/data/bot_data.db' if os.path.exists('/app/data') else 'bot_data.db'
SESSION_PATH = '/app/data/hr_session' if os.path.exists('/app/data') else 'hr_session'

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# --- [ОБМАНКА ДЛЯ RAILWAY ЧТОБЫ НЕ ВЫКЛЮЧАЛ] ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    log(f"🌍 Health-server started on port {port}")
    server.serve_forever()

# --- [БАЗА ДАННЫХ] ---
def init_db():
    if os.path.dirname(DB_PATH): os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, status TEXT)')
    conn.close()

def get_status(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT status FROM users WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        return row[0] if row else None
    except: return None

def set_status(user_id, status):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR REPLACE INTO users (user_id, status) VALUES (?, ?)", (user_id, status))
        conn.commit()
        conn.close()
    except: pass

# --- [ПРОВЕРКА ИИ] ---
async def ai_check(text, mode="is_seeker"):
    log(f"🤖 ИИ проверяет: {text[:30]}...")
    try:
        prompt = "Ты HR. Ответь ДА, если человек ищет работу. Иначе НЕТ." if mode == "is_seeker" else "Человек заинтересован? ДА или НЕТ."
        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": text}],
            max_tokens=5
        )
        ans = res.choices[0].message.content.strip().upper()
        log(f"🤖 ИИ результат: {ans}")
        return "ДА" in ans
    except Exception as e:
        log(f"❌ Ошибка ИИ: {e}")
        return True if mode == "is_interest" else False

# --- [КЛИЕНТ] ---
init_db()
# Используем обычный путь к файлу сессии
client = TelegramClient(SESSION_PATH, API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    # Логируем ВСЕ сообщения для проверки
    log(f"📩 Вижу: {event.raw_text[:20]} | Чат: {event.chat_id}")
    
    if not event.sender or event.sender.bot: return
    uid = event.sender_id

    if event.is_private:
        status = get_status(uid)
        if status in ["sent", "offered"]:
            if await ai_check(event.raw_text, "is_interest"):
                if status == "sent":
                    await event.reply("Условия: Удаленно, 2000€ + 2%. Подходит?")
                    set_status(uid, "offered")
                else:
                    await event.reply(f"Пишите куратору: {RECRUITER_TAG}")
                    set_status(uid, "final")
                    await client.send_message(REPORT_CHAT_ID, f"🔥 ЛИД: @{event.sender.username or uid}")

    elif event.is_group:
        if (datetime.now(timezone.utc) - event.date).total_seconds() > 300: return
        if await ai_check(event.raw_text, "is_seeker"):
            if get_status(uid) is None:
                log(f"🎯 ЛИД В ГРУППЕ: {uid}")
                set_status(uid, "sent")
                await asyncio.sleep(random.randint(15, 30))
                try: 
                    await client.send_message(uid, "Здравствуйте! Увидела ваш запрос в группе. У нас есть удаленка. Интересно?")
                except: log(f"❌ ЛС закрыты: {uid}")

async def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    await client.start() # Если файла нет, он попросит ввод в консоли (и упадет в Railway)
    log("🚀 БОТ ЗАПУЩЕН ЧЕРЕЗ ФАЙЛ СЕССИИ")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
