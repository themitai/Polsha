import asyncio
import os
import sqlite3
import random
import threading
from datetime import datetime, timezone

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import User
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
        log(f"💾 Статус ID {user_id} обновлен на: {status}")
    except Exception as e: log(f"❌ Ошибка БД: {e}")

# --- ИИ С УЛУЧШЕННЫМ ПОНИМАНИЕМ ---
async def ai_check(text, mode="is_seeker"):
    if not text: return False
    log(f"🔎 ИИ проверка ({mode}): {text[:50]}...")
    try:
        if mode == "is_seeker":
            sys_prompt = "Ты сильный HR. Ответь ДА, если человек САМ ищет работу или подработку или удаленную занятость. НЕТ — если это вакансия или спам."
        else:
            # Улучшенный промпт для распознавания интереса
            sys_prompt = (
                "Ты ассистент рекрутера. Клиент получил предложение работы и ответил. "
                "Он выразил интерес? (Да, расскажите, интересно, +, ок, слушаю). "
                "Если да — ответь ТОЛЬКО 'ДА'. Если нет или это спам — ответь 'НЕТ'."
            )

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
    if not event.sender_id: return
    
    # Игнорируем других ботов и каналы
    is_bot = getattr(event.sender, 'bot', False) if hasattr(event.sender, 'bot') else False
    if not isinstance(event.sender, User) or is_bot: return

    uid = event.sender_id
    text = event.raw_text.strip()
    username = f"@{event.sender.username}" if event.sender.username else f"ID: {uid}"

    # 1. ЛИЧКА (Продолжение диалога)
    if event.is_private:
        status = get_status(uid)
        log(f"📩 Сообщение в личке от {username} (Текущий статус: {status})")
        
        if status in ("sent", "offered"):
            if await ai_check(text, "is_interest"):
                if status == "sent":
                    await event.reply(
                        "💼 **Условия работы:**\n"
                        "• Удаленно (крипто-сфера)\n"
                        "• ЗП: 2000€ + 2% бонус\n"
                        "• Обучение 2-5 дня. График гибкий.\n\n"
                        "Вам подходит такое направление?"
                    )
                    set_status(uid, "offered")
                elif status == "offered":
                    await event.reply(f"Отлично! Для связи с куратором и начала обучения напишите: {RECRUITER_TAG}")
                    set_status(uid, "final")
                    await client.send_message(REPORT_CHAT_ID, f"🔥 **ЛИД ДОЖАТ:** {username}")
        return

    # 2. ГРУППЫ (Поиск новых)
    if not event.is_group: return
    if (datetime.now(timezone.utc) - event.date).total_seconds() > 600: return

    if await ai_check(text, "is_seeker") and get_status(uid) is None:
        try:
            chat = await event.get_chat()
            log(f"🎯 Лид в группе: {username}")
            
            await client.send_message(REPORT_CHAT_ID, f"🎯 **НОВЫЙ ЛИД**\n👤 {username}\n🏢 {chat.title}\n📝 {text[:100]}")
            set_status(uid, "sent")
            
            await asyncio.sleep(random.randint(20, 40))
            await client.send_message(uid, "Здравствуйте! Увидела ваш запрос в группе! У нас сейчас открыта удаленная вакансия (крипто-направление). Вам интересно узнать детали?")
            log(f"✅ Первое сообщение ушло к {username}")
        except Exception as e:
            log(f"❌ Ошибка в группе: {e}")

async def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    await client.start()
    log("🚀 БОТ ЗАПУЩЕН")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
