import asyncio
import os
import sqlite3
import random
import threading
import re
from datetime import datetime, timezone

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import User
from telethon.errors import FloodWaitError
from openai import AsyncOpenAI
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- КОНФИГУРАЦИЯ ---
API_ID = 35975193
API_HASH = '5929ba2233799d47756cfee57b71c4a5'
REPORT_CHAT_ID = 8748575384
RECRUITER_TAG = "@HRpolsha"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SESSION_STR = os.getenv("TELEGRAM_SESSION")

ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
DB_PATH = "is_seeker_v11.db"

# --- ВАРИАНТЫ ПЕРВОГО СООБЩЕНИЯ ---
FIRST_MESSAGES = [
    "Здравствуйте! Увидела ваше сообщение в группе по поводу поиска работы. У нас сейчас открыта удаленная вакансия (крипто-сфера). Вам было бы интересно узнать подробности?",
    "Добрый день! Заметила ваш пост в чате, что вы ищете работу. Подскажите, рассматриваете удаленку в крипто-проекте? Могу рассказать детали.",
    "Приветствую! Наткнулась на ваше объявление в группе. Мы как раз ищем людей на удаленную позицию в крипто-направлении. Хотели бы ознакомиться с условиями?",
    "Здравствуйте! Вы писали в группе, что ищете работу. У нас есть предложение по удаленному сотрудничеству (крипто). Если актуально, могу скинуть подробности."
]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# Функция для поиска номера телефона в тексте
def extract_phone(text):
    phone_pattern = r'\+?\d{9,15}'
    match = re.search(phone_pattern, text)
    return match.group(0) if match else "Не указан"

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
    log("📂 База данных инициализирована.")

def get_status(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT status FROM users WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        log(f"❌ Ошибка при чтении БД: {e}")
        return None

def set_status(user_id, status):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR REPLACE INTO users (user_id, status) VALUES (?, ?)", (user_id, status))
        conn.commit()
        conn.close()
        log(f"💾 Статус пользователя {user_id} обновлен на: {status}")
    except Exception as e:
        log(f"❌ Ошибка записи в БД: {e}")

# --- ИИ МОЗГ ---
async def ai_check(text, mode="is_seeker"):
    if not text or len(text) < 2: return False
    label = "ПОИСК ЛИДА" if mode == "is_seeker" else "АНАЛИЗ ИНТЕРЕСА"
    try:
        if mode == "is_seeker":
            sys_prompt = "Ты HR. Ответь ДА, только если человек САМ ищет работу. НЕТ — если это вакансия, реклама услуг или спам."
        else:
            sys_prompt = "Клиент заинтересован в предложении? Ответь ДА или НЕТ."

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
    
    # 1. ОБРАБОТКА ЛИЧНЫХ СООБЩЕНИЙ (ДОЖИМ)
    if event.is_private:
        status = get_status(uid)
        if status in ("sent", "offered"):
            if await ai_check(text, "is_interest"):
                await asyncio.sleep(random.randint(5, 12))
                try:
                    if status == "sent":
                        await event.reply("💼 **Условия:** Удаленно (крипто). ЗП 2000€ + %. Подходит?")
                        set_status(uid, "offered")
                    elif status == "offered":
                        await event.reply(f"Напишите куратору: {RECRUITER_TAG}")
                        set_status(uid, "final")
                        await client.send_message(REPORT_CHAT_ID, f"🔥 **ЛИД ДОЖАТ!**\n👤 ID: {uid}\n🔗 [ПЕРЕЙТИ К ДИАЛОГУ](tg://user?id={uid})", link_preview=False)
                except Exception as e:
                    log(f"❌ Ошибка в ЛС: {e}")
        return

    # 2. ОБРАБОТКА ГРУПП (ПОИСК)
    if event.is_group:
        if (datetime.now(timezone.utc) - event.date).total_seconds() > 600: return
        
        status = get_status(uid)
        if status is not None: return

        if await ai_check(text, "is_seeker"):
            try:
                chat = await event.get_chat()
                group_name = chat.title
                username = f"@{event.sender.username}" if event.sender.username else "Нет юзернейма"
                user_url = f"tg://user?id={uid}"
                phone_num = extract_phone(text)
                profile_phone = getattr(event.sender, 'phone', 'Скрыт')

                # Формирование ссылки на сообщение
                msg_id = event.id
                chat_id_str = str(event.chat_id).replace("-100", "")
                if hasattr(chat, 'username') and chat.username:
                    msg_link = f"https://t.me/{chat.username}/{msg_id}"
                else:
                    msg_link = f"https://t.me/c/{chat_id_str}/{msg_id}"

                log(f"🎯 ЛИД: {username} в '{group_name}'")

                # Отчет в чат-репорт
                report_text = (
                    f"🎯 **НОВЫЙ ЛИД ОБНАРУЖЕН**\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"👤 **Имя:** {event.sender.first_name or 'User'}\n"
                    f"🆔 **Аккаунт:** {username}\n"
                    f"📱 **Тел. в тексте:** `{phone_num}`\n"
                    f"📞 **Тел. в профиле:** `{profile_phone}`\n"
                    f"🏢 **Группа:** {group_name}\n"
                    f"📝 **Сообщение:** \n_{text}_\n\n"
                    f"🔗 [ПЕРЕЙТИ В ЛС (tg:// ссылка)]({user_url})\n"
                    f"🔗 [ССЫЛКА НА СООБЩЕНИЕ]({msg_link})"
                )
                
                await client.send_message(REPORT_CHAT_ID, report_text, link_preview=False)
                set_status(uid, "sent")

                # Имитация человеческой задержки
                delay = random.randint(90, 210)
                log(f"⏳ Пауза {delay} сек перед отправкой в ЛС...")
                await asyncio.sleep(delay)

                # Отправка первого сообщения
                chosen_msg = random.choice(FIRST_MESSAGES)
                await client.send_message(uid, chosen_msg)
                log(f"✅ Первое сообщение отправлено к {uid}")

            except FloodWaitError as e:
                log(f"⏳ FloodWait: ждем {e.seconds} сек.")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                log(f"❌ Ошибка: {e}")

async def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    log("🔌 Подключение...")
    await client.start()
    me = await client.get_me()
    log(f"🚀 ЗАПУЩЕНО на {me.first_name}. Мониторинг групп...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("👋 Остановлен.")
