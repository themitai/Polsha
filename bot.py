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
API_ID = 35975193
API_HASH = '5929ba2233799d47756cfee57b71c4a5'
REPORT_CHAT_ID = 8748575384
RECRUITER_TAG = "@HRpolsha"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SESSION_STR = os.getenv("TELEGRAM_SESSION")

ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
DB_PATH = "leads_v4.db"

# --- ВАРИАНТЫ ПЕРВОГО СООБЩЕНИЯ ---
FIRST_MESSAGES = [
    "Здравствуйте! Увидела ваше сообщение в группе Вам было бы интересно узнать подробности?",
    "Добрый день! Заметила ваш пост в чате, Могу рассказать детали.",
    "Приветствую! Наткнулась на ваше объявление в группе.  Хотели бы ознакомиться с условиями?",
    "Здравствуйте! Вы писали в группе Если актуально, могу скинуть подробности."
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
    log(f"🧠 ИИ ({label}) проверяет текст: {text[:60]}...")
    
    try:
        if mode == "is_seeker":
            sys_prompt = "Ты HR. Ответь ДА, только если человек САМ ищет работу или пеший переход, приехал сегодня, очередь на границе, еду в польшу, выезжаю из, карта побыту, мельдунок, pesel, подача на карту, виза закончилась, ищу жилье, сниму квартиру, нужна комната, ищу кавалерку, ищу работу, шукаю роботу, подработка, підробіток, детский сад, садик, школа для ребенка, dobry start. НЕТ — если это вакансия, реклама услуг или спам."
        else:
            sys_prompt = "Клиент заинтересован в предложении? Ответь ДА или НЕТ."

        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}],
            max_tokens=5, temperature=0
        )
        ans = res.choices[0].message.content.strip().upper()
        
        is_positive = "ДА" in ans
        log(f"🤖 Вердикт ИИ: {'✅ ДА' if is_positive else '❌ НЕТ'} (ответ: {ans})")
        return is_positive
    except Exception as e:
        log(f"❌ Ошибка ИИ: {e}")
        return False

# --- ОБРАБОТЧИК ---
init_db()
client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    if not event.sender_id: return
    
    # Игнорируем ботов
    is_bot = getattr(event.sender, 'bot', False) if hasattr(event.sender, 'bot') else False
    if not isinstance(event.sender, User) or is_bot: return

    uid = event.sender_id
    text = event.raw_text.strip()
    
    # 1. ЛИЧНЫЕ СООБЩЕНИЯ
    if event.is_private:
        status = get_status(uid)
        if status in ("sent", "offered"):
            log(f"📩 Получено ЛС от пользователя {uid}. Статус в базе: {status}")
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
                except FloodWaitError as e:
                    log(f"⏳ FloodWait в ЛС: ждем {e.seconds} сек.")
                    await asyncio.sleep(e.seconds)
        return

    # 2. ГРУППЫ
    if event.is_group:
        # Логируем только подозрительно короткие или длинные интервалы (для контроля работы)
        if (datetime.now(timezone.utc) - event.date).total_seconds() > 600:
            return # Старые сообщения не трогаем

        # Вызываем ИИ только если пользователя нет в базе
        status = get_status(uid)
        if status is not None:
            return # Мы уже работали с ним

        if await ai_check(text, "is_seeker"):
            try:
                chat = await event.get_chat()
                group_name = chat.title
                username = f"@{event.sender.username}" if event.sender.username else f"ID: {uid}"
                user_url = f"tg://user?id={uid}"
                
                # Ссылка на сообщение
                msg_id = event.id
                chat_id = str(event.chat_id).replace("-100", "")
                if hasattr(chat, 'username') and chat.username:
                    msg_link = f"https://t.me/{chat.username}/{msg_id}"
                else:
                    msg_link = f"https://t.me/c/{chat_id}/{msg_id}"

                log(f"🎯 ЛИД ПОДТВЕРЖДЕН: {username} в группе '{group_name}'")

                # Отчет
                report_text = (
                    f"🎯 **ЛИД НАЙДЕН**\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"👤 Имя: {event.sender.first_name or '—'}\n"
                    f"🆔 ID: `{uid}`\n"
                    f"🔗 Прямая ссылка: [Открыть чат]({user_link})\n"
                    f"🏠 Группа: {chat.title}\n"
                    f"💬 {text[:180]}\n"
                    f"🔍 Триггер: {matched_trigger}"
                )
                
                await client.send_message(REPORT_CHAT_ID, report_text, link_preview=False)
                set_status(uid, "sent")

                # Безопасная пауза
                delay = random.randint(90, 210)
                log(f"⏳ Имитация раздумий: пауза {delay} сек перед отправкой сообщения {username}...")
                await asyncio.sleep(delay)

                # Обновляем сущность пользователя (защита от PeerUser error)
                log(f"🔍 Обновление данных пользователя {uid} перед отправкой...")
                input_peer = await client.get_input_entity(uid)
                
                # Отправка
                chosen_msg = random.choice(FIRST_MESSAGES)
                await client.send_message(input_peer, chosen_msg)
                log(f"✅ Сообщение успешно отправлено в ЛС к {username}")

            except FloodWaitError as e:
                log(f"⚠️ Остановка потока: Telegram FloodWait на {e.seconds} сек.")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                log(f"❌ Ошибка при обработке лида {uid}: {e}")

async def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    log("🔌 Подключение к Telegram...")
    await client.start()
    
    me = await client.get_me()
    log(f"🚀 БОТ ЗАПУЩЕН на аккаунте: {me.first_name} (@{me.username or 'no_user'})")
    log("👀 Мониторинг групп начат...")
    
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("👋 Бот остановлен вручную.")
