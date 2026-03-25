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
DB_PATH = os.getenv("DB_PATH", "bot_data.db")

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# --- УЛУЧШЕННЫЙ HEALTH SERVER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"OK") # Railway ждет любой ответ 200 OK

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    log(f"🌍 Health-server запущен на порту {port}")
    server.serve_forever()

# --- БАЗА ДАННЫХ ---
def init_db():
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
    except Exception as e: log(f"Ошибка БД: {e}")

# --- ИИ ---
async def ai_check(text, mode="is_seeker"):
    log(f"🔎 ИИ ({mode}): {text[:50]}...")
    try:
        if mode == "is_seeker":
            sys_prompt = (
                "Ты HR-фильтр. Отвечай ТОЛЬКО 'ДА' или 'НЕТ'. "
                "ДА — человек САМ ищет работу (пишет: ищу работу, нужна подработка). "
                "НЕТ — человек предлагает работу или услуги."
            )
        else:
            sys_prompt = "Клиент заинтересован? Ответь ДА или НЕТ."

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

# --- ПРОВЕРКА ПРИ ЗАПУСКЕ ---
async def startup_check(client):
    log("🛠 Самодиагностика...")
    msg = "🚀 **Бот запущен и мониторит чаты!**\nТест ИИ пройден."
    await client.send_message(REPORT_CHAT_ID, msg)

# --- ОБРАБОТЧИК ---
init_db()
client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    if not event.sender or event.sender.bot: return
    uid = event.sender_id
    text = event.raw_text.strip()
    username = f"@{event.sender.username}" if event.sender.username else f"ID: {uid}"

    # ЛИЧКА
    if event.is_private:
        status = get_status(uid)
        if status in ("sent", "offered"):
            if await ai_check(text, "is_interest"):
                if status == "sent":
                    await event.reply("💼 **Условия:** Удаленно, крипто. ЗП 2000€ + %. Подходит?")
                    set_status(uid, "offered")
                elif status == "offered":
                    await event.reply(f"Напишите куратору: {RECRUITER_TAG}")
                    set_status(uid, "final")
                    await client.send_message(REPORT_CHAT_ID, f"🔥 ЛИД ГОТОВ: {username}")
        return

    # ГРУППЫ
    if not event.is_group: return
    if (datetime.now(timezone.utc) - event.date).total_seconds() > 600: return

    if await ai_check(text, "is_seeker"):
        # Если статуса нет — значит это новый соискатель
        if get_status(uid) is None:
            try:
                chat = await event.get_chat()
                log(f"🎯 Нашел соискателя: {username}")
                
                # Отправляем отчет
                report = f"🎯 **НОВЫЙ ЛИД**\n👤 {username}\n🏢 {chat.title}\n📝 {text[:100]}"
                await client.send_message(REPORT_CHAT_ID, report)

                set_status(uid, "sent")
                await asyncio.sleep(random.randint(30, 60))
                await client.send_message(uid, "Здравствуйте! Увидела ваш запрос в группе. У нас сейчас открыта удаленная вакансия. Интересно узнать детали?")
            except Exception as e:
                log(f"❌ Ошибка отправки: {e}")

async def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    await client.start()
    await startup_check(client)
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
