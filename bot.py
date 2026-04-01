import asyncio
import os
import sqlite3
import random
import threading
from datetime import datetime, timezone

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from openai import AsyncOpenAI
from http.server import BaseHTTPRequestHandler, HTTPServer

# ========================= НОВЫЕ ДАННЫЕ =========================
API_ID = 38994094
API_HASH = 'ece2cfe429e0150d7792c371fe5302b8'
REPORT_CHAT_ID = 8119593834
RECRUITER_TAG = "@ShamilGegman"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SESSION_STR = os.getenv("TELEGRAM_SESSION")

ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
DB_PATH = "leads_v2.db"

# ====================== ТРИГГЕРЫ ======================
TRIGGER_WORDS = [
    # Переезд и документы
    "приехал сегодня", "очередь на границе", "пеший переход", "еду в польшу", "выезжаю из",
    "карта побыту", "мельдунок", "pesel", "подача на карту", "виза закончилась", "освядчение",
    "karta pobytu", "meldunek",

    # Жильё
    "ищу жилье", "сниму квартиру", "нужна комната", "ищу кавалерку", "жилье посуточно",
    "зніму квартиру", "шукаю житло", "mieszkanie", "kawalerka",

    # Работа и подработка
    "ищу работу", "шукаю роботу", "подработка", "підробіток", "работа без языка",
    "работа водителем", "код 95", "тахограф",

    # Медицина и дети
    "детский сад", "садик", "школа для ребенка", "800+", "dobry start", "przedszkole",
    "русскоговорящий врач", "поликлиника", "няня"
]

STOP_WORDS = [
    "ищем", "требуется", "вакансия", "набираем", "предлагаем", "услуги", "помогу",
    "пробив", "оформлю", "сдаю", "аренда от", "работа для девушек"
]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ====================== БАЗА ДАННЫХ ======================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, status TEXT, first_contact TEXT)')
    conn.close()

def get_status(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT status FROM users WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        return row[0] if row else None
    except:
        return None

def set_status(user_id, status):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR REPLACE INTO users (user_id, status, first_contact) VALUES (?, ?, ?)",
                     (user_id, status, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except:
        pass

# ====================== ИИ С ПОДРОБНЫМ ЛОГИРОВАНИЕМ ======================
async def ai_check(text, mode="is_lead"):
    if not text or len(text) < 3:
        return False

    label = "ПОИСК ЛИДА" if mode == "is_lead" else "АНАЛИЗ ИНТЕРЕСА"
    log(f"🧠 ИИ [{label}] → Анализирую текст: {text[:80]}...")

    try:
        if mode == "is_lead":
            sys_prompt = (
                "Ты — строгий HR-аналитик. Ответь ТОЛЬКО одним словом: ДА или НЕТ.\n"
                "ДА — если человек имеет реальную проблему и ищет решение (жильё, работа, документы, переезд, медицина, пособия и т.д.)\n"
                "НЕТ — если это вакансия, реклама услуг, спам или предложение."
            )
        else:
            sys_prompt = (
                "Человек проявил интерес к предложению помощи? "
                "Ответы вроде 'да', 'интересно', 'расскажи', 'подходит', 'хочу' — это ДА.\n"
                "Ответь ТОЛЬКО ДА или НЕТ."
            )

        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": text}
            ],
            max_tokens=10,
            temperature=0.0
        )

        answer = res.choices[0].message.content.strip().upper()
        decision = "✅ ДА" if "ДА" in answer else "❌ НЕТ"

        log(f"🤖 ИИ РЕШЕНИЕ [{label}]: {decision} | Ответ ИИ: '{answer}'")
        return "ДА" in answer

    except Exception as e:
        log(f"❌ Ошибка OpenAI: {e}")
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

    # === ЛИЧНЫЕ СООБЩЕНИЯ ===
    if event.is_private:
        status = get_status(uid)
        if status in ("sent", "offered"):
            log(f"📩 ЛС от {uid} | Статус: {status} | Текст: {text[:70]}...")
            if await ai_check(text, "is_interest"):
                if status == "sent":
                    await event.reply("💼 У нас есть удалённая позиция в крипто-сфере. ЗП 2000€ + %. Подходит?")
                    set_status(uid, "offered")
                elif status == "offered":
                    await event.reply(f"Отлично! Напишите куратору: {RECRUITER_TAG}")
                    set_status(uid, "final")
                    await client.send_message(REPORT_CHAT_ID, f"🔥 ЛИД ДОЖАТ! ID: {uid}")
        return

    # === ГРУППЫ ===
    if not event.is_group:
        return
    if (datetime.now(timezone.utc) - event.date).total_seconds() > 600:
        return

    # Фильтрация
    if any(word in text_lower for word in STOP_WORDS):
        return

    if any(word in text_lower for word in TRIGGER_WORDS):
        if get_status(uid) is None:
            if await ai_check(text, "is_lead"):
                try:
                    chat = await event.get_chat()
                    username = f"@{event.sender.username}" if event.sender.username else f"ID:{uid}"
                    msg_link = f"https://t.me/c/{str(event.chat_id)[4:]}/{event.id}"

                    report = (
                        f"🎯 **НОВЫЙ ЛИД**\n"
                        f"👤 {event.sender.first_name or '—'} ({username})\n"
                        f"🏠 Группа: {chat.title}\n"
                        f"💬 {text[:200]}\n"
                        f"🔗 [Ссылка]({msg_link})"
                    )

                    await client.send_message(REPORT_CHAT_ID, report, link_preview=False)

                    set_status(uid, "sent")
                    await asyncio.sleep(random.randint(60, 180))

                    first_msg = random.choice([
                        "Здравствуйте! Видела ваше сообщение. У вас вопрос с жильём, работой или документами?",
                        "Добрый день! Заметила, что вы ищете решение по переезду или жилью. Могу подсказать варианты."
                    ])

                    await client.send_message(uid, first_msg)
                    log(f"✅ Первое сообщение отправлено пользователю {uid}")

                except Exception as e:
                    log(f"❌ Ошибка при обработке лида {uid}: {e}")

# ====================== ЗАПУСК ======================
async def main():
    # Health check
    def health_server():
        port = int(os.getenv("PORT", 8080))
        server = HTTPServer(('0.0.0.0', port), 
            type('H', (BaseHTTPRequestHandler,), {'do_GET': lambda s: (s.send_response(200), s.end_headers(), s.wfile.write(b"OK"))}))
        server.serve_forever()

    threading.Thread(target=health_server, daemon=True).start()

    await client.start()
    me = await client.get_me()
    log(f"🚀 Бот запущен на аккаунте: {me.first_name} (@{me.username or 'no_username'})")
    log("🎯 Режим: Поиск лидов по триггерам (переезд, жильё, работа и т.д.)")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
