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

# ========================= ТВОИ ДАННЫЕ =========================
API_ID = 38165468
API_HASH = '387dc50469f115c50fc7a4f36a9b84b3'
REPORT_CHAT_ID = 8348598832
RECRUITER_TAG = "@botlooklead"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SESSION_STR = os.getenv("TELEGRAM_SESSION")

ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
DB_PATH = "leads_v3.db"

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
    conn.execute('CREATE TABLE IF NOT EXISTS leads (user_id INTEGER PRIMARY KEY, status TEXT, category TEXT)')
    conn.close()

def get_status(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT status FROM leads WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        return row[0] if row else None
    except:
        return None

def set_status(user_id, status, category="unknown"):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR REPLACE INTO leads (user_id, status, category) VALUES (?, ?, ?)",
                     (user_id, status, category))
        conn.commit()
        conn.close()
    except:
        pass

# ====================== ИИ ======================
async def ai_check(text, mode="is_lead"):
    if not ai_client:
        return True
    try:
        prompt = "Ответь ТОЛЬКО ДА или НЕТ. ДА — если человек ищет помощь (жильё, работа, документы, переезд и т.д.)"
        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": text}],
            max_tokens=5,
            temperature=0
        )
        answer = res.choices[0].message.content.strip().upper()
        log(f"🧠 ИИ [{mode}]: {answer}")
        return "ДА" in answer
    except Exception as e:
        log(f"❌ Ошибка ИИ: {e}")
        return False

# ====================== ОБРАБОТЧИК ======================
init_db()
client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    if not event.sender_id or getattr(event.sender, 'bot', False):
        return

    uid = event.sender_id
    text = event.raw_text.strip()
    text_lower = text.lower()

    log(f"📨 Сообщение от {uid} | Текст: {text[:70]}...")

    if event.is_private:
        status = get_status(uid)
        if status in ("sent", "offered"):
            if await ai_check(text, "is_interest"):
                if status == "sent":
                    await event.reply("💼 У нас есть удалённая позиция в крипто-сфере. ЗП 2000€ + %. Подходит?")
                    set_status(uid, "offered")
                elif status == "offered":
                    await event.reply(f"Отлично! Напишите куратору: {RECRUITER_TAG}")
                    set_status(uid, "final")
        return

    if not event.is_group:
        return
    if (datetime.now(timezone.utc) - event.date).total_seconds() > 600:
        return

    if any(word in text_lower for word in STOP_WORDS):
        return

    matched_trigger = next((word for word in TRIGGER_WORDS if word in text_lower), None)

    if matched_trigger and get_status(uid) is None:
        if await ai_check(text, "is_lead"):
            try:
                # Получаем информацию о пользователе
                user = await client.get_entity(uid)
                chat = await event.get_chat()

                username = f"@{user.username}" if user.username else "Нет username"
                phone = getattr(user, 'phone', None) or "Скрыт"
                user_link = f"tg://user?id={uid}"

                report = (
                    f"🎯 **ЛИД НАЙДЕН**\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"👤 Имя: {user.first_name or '—'}\n"
                    f"🆔 ID: `{uid}`\n"
                    f"📱 Телефон: {phone}\n"
                    f"🔗 Прямая ссылка на профиль: [Открыть чат]({user_link})\n"
                    f"🏠 Группа: {chat.title}\n"
                    f"💬 Сообщение: {text[:200]}\n"
                    f"🔍 Триггер: {matched_trigger}"
                )

                await client.send_message(REPORT_CHAT_ID, report, link_preview=False)
                log(f"✅ Отчёт о лиде отправлен в REPORT_CHAT_ID")

                set_status(uid, "sent")

                await asyncio.sleep(random.randint(50, 160))

                await client.send_message(uid, "Здравствуйте! Видела ваше сообщение. Могу подсказать варианты по вашему вопросу.")
                log(f"✅ Первое сообщение отправлено пользователю {uid}")

            except FloodWaitError as e:
                log(f"⏳ FloodWait: ждём {e.seconds} сек")
                await asyncio.sleep(e.seconds)
            except UserIsBlockedError:
                log(f"⛔ Пользователь {uid} заблокировал бота")
            except Exception as e:
                log(f"❌ Ошибка при обработке лида {uid}: {e}")

# ====================== ЗАПУСК ======================
async def main():
    def health():
        port = int(os.getenv("PORT", 8080))
        server = HTTPServer(('0.0.0.0', port),
            type('H', (BaseHTTPRequestHandler,), {'do_GET': lambda s: (s.send_response(200), s.end_headers(), s.wfile.write(b"OK"))}))
        server.serve_forever()
    threading.Thread(target=health, daemon=True).start()

    await client.start()
    me = await client.get_me()
    log(f"🚀 Бот запущен на аккаунте: {me.first_name} (@{me.username or '—'})")
    log("🎯 Режим: Lead Generator v3.7 — с прямой ссылкой и телефоном")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
