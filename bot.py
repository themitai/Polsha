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

# --- КОНФИГУРАЦИЯ ---
API_ID = 35523804
API_HASH = 'ff7673ebc0e925a32fb52693bdfae16f'
REPORT_CHAT_ID = 7238685565
RECRUITER_TAG = "@hannaober"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SESSION_STR = os.getenv("TELEGRAM_SESSION")

ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
DB_PATH = '/app/data/bot_data.db' if os.path.exists('/app/data') else 'bot_data.db'

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# --- HEALTH SERVER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args): return

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# --- БАЗА ДАННЫХ ---
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
    except Exception as e: log(f"❌ Ошибка БД: {e}")

# --- ИИ ---
async def ai_check(text, mode="is_seeker"):
    log(f"🔎 ИИ ({mode}): {text[:40]}...")
    try:
        sys_prompt = "Ты HR. Ответь ДА, только если человек САМ ищет работу. НЕТ — если это вакансия или реклама." if mode == "is_seeker" else "Человек заинтересован? Ответь ДА или НЕТ."
        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}],
            max_tokens=5, temperature=0
        )
        ans = res.choices[0].message.content.strip().upper()
        log(f"✅ ИИ вердикт: {ans}")
        return "ДА" in ans
    except Exception as e:
        log(f"❌ Ошибка ИИ: {e}")
        return False

# --- ОБРАБОТЧИК ---
init_db()
client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    if not event.sender_id or (event.sender and event.sender.bot): return
    
    uid = event.sender_id
    text = event.raw_text.strip()
    
    # 1. ОБРАБОТКА ЛИЧКИ
    if event.is_private:
        status = get_status(uid)
        if status in ("sent", "offered") and await ai_check(text, "is_interest"):
            if status == "sent":
                await event.reply("💼 **Условия:** Удаленно, крипто. ЗП 2000€ + %. Подходит?")
                set_status(uid, "offered")
            elif status == "offered":
                await event.reply(f"Напишите куратору: {RECRUITER_TAG}")
                set_status(uid, "final")
                await client.send_message(REPORT_CHAT_ID, f"🔥 ЛИД ГОТОВ: ID {uid}")
        return

    # 2. ОБРАБОТКА ГРУПП
    if not event.is_group: return
    if (datetime.now(timezone.utc) - event.date).total_seconds() > 600: return

    # Если ИИ сказал ДА и мы еще не писали этому человеку
    if await ai_check(text, "is_seeker") and get_status(uid) is None:
        log(f"🎯 Лид подтвержден ИИ. Начинаю процесс отправки для ID: {uid}")
        try:
            # Получаем полные данные пользователя, чтобы Телеграм разрешил отправить ЛС
            user = await event.get_sender()
            username = f"@{user.username}" if user.username else f"ID: {uid}"
            chat = await event.get_chat()
            
            # Отчет в канал
            await client.send_message(REPORT_CHAT_ID, f"🎯 **НОВЫЙ ЛИД**\n👤 {username}\n🏢 {chat.title}\n📝 {text[:100]}")
            
            # Ставим статус, чтобы не писать дважды
            set_status(uid, "sent")
            
            # Небольшая пауза
            log(f"⏳ Ждем 20 сек перед отправкой к {username}...")
            await asyncio.sleep(20)
            
            # Отправка в ЛС
            await client.send_message(user, "Здравствуйте! Увидела ваш запрос в группе. У нас сейчас открыта удаленная вакансия. Вам интересно узнать детали?")
            log(f"✅ СООБЩЕНИЕ УШЛО К {username}")
            
        except Exception as e:
            log(f"❌ ОШИБКА ПРИ ОТПРАВКЕ: {e}")
            await client.send_message(REPORT_CHAT_ID, f"⚠️ Ошибка ЛС для {uid}: `{str(e)}`")

async def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    await client.start()
    log("🚀 БОТ ЗАПУЩЕН")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
