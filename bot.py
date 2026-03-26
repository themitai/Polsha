import asyncio
import os
import sqlite3
import random
import threading
from datetime import datetime, timezone

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import User, Channel, Chat
from telethon.errors import FloodWaitError
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
DB_PATH = "is_seeker_v10.db"

# --- ВАРИАНТЫ ПЕРВОГО СООБЩЕНИЯ (РАНДОМИЗАЦИЯ) ---
FIRST_MESSAGES = [
    "Здравствуйте! Увидела ваше сообщение в группе по поводу поиска работы. У нас сейчас открыта удаленная вакансия (крипто-сфера). Вам было бы интересно узнать подробности?",
    "Добрый день! Заметила ваш пост в чате, что вы ищете работу. Подскажите, рассматриваете удаленку в крипто-проекте? Могу рассказать детали.",
    "Приветствую! Наткнулась на ваше объявление в группе. Мы как раз ищем людей на удаленную позицию в крипто-направлении. Хотели бы ознакомиться с условиями?",
    "Здравствуйте! Вы писали в группе, что ищете работу. У нас есть предложение по удаленному сотрудничеству (крипто). Если актуально, могу скинуть подробности."
]

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

# --- ИИ МОЗГ ---
async def ai_check(text, mode="is_seeker"):
    if not text or len(text) < 2: return False
    try:
        sys_prompt = "Ты HR. Ответь ДА, только если человек САМ ищет работу. НЕТ — вакансия или спам." if mode == "is_seeker" else "Клиент заинтересован в предложении? Ответь ДА или НЕТ."
        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}],
            max_tokens=5, temperature=0
        )
        ans = res.choices[0].message.content.strip().upper()
        return "ДА" in ans
    except Exception as e:
        log(f"❌ Ошибка ИИ: {e}")
        return False

# --- ОБРАБОТЧИК ---
init_db()
client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    if not event.sender_id: return
    is_bot = getattr(event.sender, 'bot', False) if hasattr(event.sender, 'bot') else False
    if not isinstance(event.sender, User) or is_bot: return

    uid = event.sender_id
    text = event.raw_text.strip()
    
    # Ссылки и данные
    first_name = event.sender.first_name or "User"
    username = f"@{event.sender.username}" if event.sender.username else f"ID: {uid}"
    user_url = f"tg://user?id={uid}"

    # 1. ЛИЧНЫЕ СООБЩЕНИЯ (Диалог)
    if event.is_private:
        status = get_status(uid)
        if status in ("sent", "offered") and await ai_check(text, "is_interest"):
            await asyncio.sleep(random.randint(5, 12))
            try:
                if status == "sent":
                    await event.reply("💼 **Условия:** Удаленно (крипто). ЗП 2000€ + %. Подходит?")
                    set_status(uid, "offered")
                elif status == "offered":
                    await event.reply(f"Напишите куратору: {RECRUITER_TAG}")
                    set_status(uid, "final")
                    await client.send_message(REPORT_CHAT_ID, f"🔥 **ЛИД ДОЖАТ!**\n👤 {first_name} ({username})\n🔗 [ПЕРЕЙТИ К ДИАЛОГУ]({user_url})", link_preview=False)
            except FloodWaitError as e: await asyncio.sleep(e.seconds)
        return

    # 2. ГРУППЫ (Поиск)
    if event.is_group:
        if (datetime.now(timezone.utc) - event.date).total_seconds() > 600: return

        if await ai_check(text, "is_seeker") and get_status(uid) is None:
            try:
                chat = await event.get_chat()
                group_name = chat.title
                
                # Ссылка на сообщение (валидна для публичных групп и супергрупп)
                msg_id = event.id
                if hasattr(chat, 'username') and chat.username:
                    msg_link = f"https://t.me/{chat.username}/{msg_id}"
                else:
                    # Для закрытых групп ссылка через ID чата
                    chat_id = str(event.chat_id).replace("-100", "")
                    msg_link = f"https://t.me/c/{chat_id}/{msg_id}"

                log(f"🎯 Лид в {group_name}: {username}")

                # Формируем отчет
                report_text = (
                    f"🎯 **НОВЫЙ ЛИД ОБНАРУЖЕН**\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"👤 **Имя:** {first_name}\n"
                    f"🆔 **Аккаунт:** [{username}]({user_url})\n"
                    f"🏢 **Группа:** {group_name}\n"
                    f"📝 **Сообщение:** \n_{text}_\n\n"
                    f"🔗 [ССЫЛКА НА СООБЩЕНИЕ]({msg_link})"
                )
                
                await client.send_message(REPORT_CHAT_ID, report_text, link_preview=False)
                set_status(uid, "sent")

                # Пауза перед ЛС
                delay = random.randint(80, 200)
                log(f"⏳ Пауза {delay} сек перед ЛС для {username}...")
                await asyncio.sleep(delay)

                # Отправка случайного приветствия
                await client.send_message(uid, random.choice(FIRST_MESSAGES))
                log(f"✅ Сообщение отправлено к {username}")

            except FloodWaitError as e:
                log(f"⚠️ Ждем {e.seconds} сек (FloodWait)")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                log(f"❌ Ошибка: {e}")

async def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    await client.start()
    log("🚀 БОТ ЗАПУЩЕН")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
