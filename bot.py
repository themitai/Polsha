import asyncio
import os
import sqlite3
import random
import threading
from datetime import datetime, timezone
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from openai import AsyncOpenAI
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- [КОНФИГУРАЦИЯ] ---
API_ID = 35523804
API_HASH = 'ff7673ebc0e925a32fb52693bdfae16f'
REPORT_CHAT_ID = 7238685565
RECRUITER_TAG = "@hannaober"

# Берем данные из секретов Railway
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SESSION_STR = os.getenv("TELEGRAM_SESSION")

ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
DB_PATH = '/app/data/bot_data.db' if os.path.exists('/app/data') else 'bot_data.db'

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

# --- [ПРОВЕРКА ИИ С ДИАГНОСТИКОЙ] ---
async def ai_check(text, mode="is_seeker"):
    log(f"🔎 ПРОВЕРКА ИИ: '{text[:30]}...'")
    if not OPENAI_API_KEY:
        log("❌ ОШИБКА: OPENAI_API_KEY не задан в Railway!")
        return True if mode == "is_interest" else False

    try:
        prompt = "Ты HR. Ответь ДА, если человек ищет работу. Иначе НЕТ." if mode == "is_seeker" else "Человек проявил интерес? ДА или НЕТ."
        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": text}],
            max_tokens=5, timeout=15
        )
        ans = res.choices[0].message.content.strip().upper()
        log(f"✅ ИИ ОТВЕТИЛ: {ans}")
        return "ДА" in ans
    except Exception as e:
        log(f"❌ ОШИБКА ИИ: {e}")
        # Если ИИ упал, в личке отвечаем "Да" на всякий случай, в группах - игнорим
        return True if mode == "is_interest" else False

# --- [ОСНОВНОЙ КЛИЕНТ] ---
init_db()
if not SESSION_STR:
    log("❌ КРИТИЧЕСКАЯ ОШИБКА: TELEGRAM_SESSION пуста! Бот не запустится.")
    # Мы не вызываем sys.exit, чтобы контейнер не перезагружался бесконечно
    client = None
else:
    client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    if not event.sender or event.sender.bot: return
    uid = event.sender_id

    # Лог для проверки, что бот вообще "слышит" сообщения
    log(f"📩 Вижу сообщение от {uid} ({'ЛС' if event.is_private else 'Группа'})")

    if event.is_private:
        status = get_status(uid)
        if status in ["sent", "offered"]:
            if await ai_check(event.raw_text, "is_interest"):
                if status == "sent":
                    await event.reply("💼 Удаленно, крипто. ЗП: 2000€ + 2%. Обучение 2 дня. Подходит?")
                    set_status(uid, "offered")
                else:
                    await event.reply(f"Отлично! Пишите куратору Ханне: {RECRUITER_TAG}")
                    set_status(uid, "final")
                    await client.send_message(REPORT_CHAT_ID, f"🔥 ЛИД ГОТОВ: @{event.sender.username or uid}")

    elif event.is_group:
        # Пропускаем старые сообщения (более 5 минут)
        if (datetime.now(timezone.utc) - event.date).total_seconds() > 300: return
        
        if await ai_check(event.raw_text, "is_seeker"):
            if get_status(uid) is None:
                log(f"🎯 НАЙДЕН ЛИД В ГРУППЕ: {uid}")
                set_status(uid, "sent")
                await asyncio.sleep(random.randint(20, 45))
                try: 
                    await client.send_message(uid, "Здравствуйте! Увидела ваш запрос в группе. У нас есть удаленка (крипто). Интересно узнать детали?")
                    log(f"✅ Первое сообщение отправлено {uid}")
                except: 
                    log(f"❌ Не удалось написать {uid} (закрыто ЛС)")

async def main():
    # Запускаем сервер, чтобы Railway видел порт 8080
    threading.Thread(target=run_health_server, daemon=True).start()
    
    if client:
        await client.start()
        log("🚀 БОТ УСПЕШНО ЗАПУЩЕН И СЛУШАЕТ ЧАТЫ")
        await client.run_until_disconnected()
    else:
        log("😴 Бот в режиме ожидания. Вставьте TELEGRAM_SESSION в Railway.")
        while True: await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
