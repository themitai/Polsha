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
        self.wfile.write(b"WORKING")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# --- БАЗА ДАННЫХ ---
def init_db():
    if os.path.dirname(DB_PATH):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
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
    except Exception as e: log(f"Ошибка SQLite: {e}")

# --- ИИ С ЖЕСТКИМИ ПРАВИЛАМИ ---
async def ai_check(text, mode="is_seeker"):
    log(f"🔎 ИИ ({mode}): {text[:50]}...")
    try:
        if mode == "is_seeker":
            sys_prompt = (
                "Ты — HR-ассистент. Твоя цель: найти только людей, которые пишут 'Ищу работу', 'Нужна подработка'. "
                "ОТВЕЧАЙ 'НЕТ', ЕСЛИ: "
                "1. Это вакансия (Ищем, Требуются, Работа в...). "
                "2. Это реклама услуг (Ремонт, Переезды, Документы). "
                "3. Это спам или новости. "
                "ОТВЕЧАЙ 'ДА', ТОЛЬКО ЕСЛИ: человек пишет от своего имени, что ему нужна работа. "
                "Отвечай ТОЛЬКО одним словом: ДА или НЕТ."
            )
        else:
            sys_prompt = "Клиент согласен на условия или просит подробности? Ответь ДА или НЕТ."

        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}],
            max_tokens=5, temperature=0
        )
        ans = res.choices[0].message.content.strip().upper()
        log(f"✅ ИИ вердикт: {ans}")
        return "ДА" in ans
    except Exception as e:
        log(f"❌ Ошибка OpenAI: {e}")
        return False

# --- ПРОВЕРКА СИСТЕМЫ ПРИ ЗАПУСКЕ ---
async def startup_check(client):
    log("🛠 Запуск самодиагностики...")
    test_text = "Ищу работу водителем в Берлине"
    ai_ok = await ai_check(test_text, "is_seeker")
    
    status_emoji = "✅" if ai_ok else "⚠️"
    status_text = "ИИ работает корректно" if ai_ok else "ИИ ошибается или не отвечает"
    
    msg = (
        f"🚀 **Бот-HR успешно запущен!**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{status_emoji} **Проверка ИИ:** {status_text}\n"
        f"📂 **База данных:** Подключена\n"
        f"🎯 **Режим:** Строгий поиск соискателей\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Бот начал мониторинг чатов..."
    )
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
                    await event.reply("💼 **Условия работы:**\n• Удаленно (крипто)\n• ЗП: 2000€ + 2% бонус\n• Обучение 2 дня.\n\nВам подходит?")
                    set_status(uid, "offered")
                elif status == "offered":
                    await event.reply(f"Отлично! Напишите куратору: {RECRUITER_TAG}")
                    set_status(uid, "final")
                    await client.send_message(REPORT_CHAT_ID, f"🔥 **ЛИД ДОЖАТ:** {username}")
        return

    # ГРУППЫ
    if not event.is_group: return
    if (datetime.now(timezone.utc) - event.date).total_seconds() > 600: return

    if await ai_check(text, "is_seeker"):
        if get_status(uid) is None:
            try:
                chat = await event.get_chat()
                msg_link = f"https://t.me/c/{str(event.chat_id).replace('-100', '')}/{event.id}" if not chat.username else f"https://t.me/{chat.username}/{event.id}"
                
                # Отчет в канал
                report = (
                    f"🎯 **НАЙДЕН СОИСКАТЕЛЬ**\n"
                    f"👤 **КТО:** {event.sender.first_name} ({username})\n"
                    f"🏢 **ГДЕ:** {chat.title}\n"
                    f"📝 **ТЕКСТ:** _{text[:150]}_\n"
                    f"🔗 [ОТКРЫТЬ]({msg_link})"
                )
                await client.send_message(REPORT_CHAT_ID, report, link_preview=False)

                set_status(uid, "sent")
                await asyncio.sleep(random.randint(30, 60))
                await client.send_message(uid, "Здравствуйте! Увидела ваш запрос в группе. У нас сейчас открыта удаленная вакансия. Вам интересно узнать детали?")
            except Exception as e:
                if "privacy" in str(e).lower():
                    await client.send_message(REPORT_CHAT_ID, f"⚠️ У {username} закрыта личка.")

# --- МЕЙН ---
async def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    await client.start()
    await startup_check(client) # Отправка уведомления в чат
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
