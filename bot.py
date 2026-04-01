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

# ========================= КОНФИГУРАЦИЯ =========================
API_ID = 38994094
API_HASH = 'ece2cfe429e0150d7792c371fe5302b8'
REPORT_CHAT_ID = 8119593834
RECRUITER_TAG = "@ShamilGegman"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SESSION_STR = os.getenv("TELEGRAM_SESSION")

ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
DB_PATH = "leads_v2.db"

# ====================== ТРИГГЕРЫ ДЛЯ ПОИСКА ======================
TRIGGER_WORDS = {
    "high_priority": [
        # Переезд и документы
        "приехал сегодня", "очередь на границе", "пеший переход", "еду в польшу", "выезжаю из",
        "карта побыту", "мельдунок", "pesel ukr", "подача на карту", "виза закончилась",
        # Жильё
        "ищу жилье", "сниму квартиру", "нужна комната", "ищу кавалерку", "жилье посуточно",
        "зніму квартиру", "шукаю житло", "mieszkanie", "kawalerka",
        # Работа
        "ищу работу", "шукаю роботу", "подработка", "підробіток", "работа без языка",
        # Медицина и дети
        "детский сад", "садик", "школа для ребенка", "800+", "dobry start", "przedszkole"
    ],
    "medium_priority": [
        "перевезти вещи", "работа водителем", "код 95", "тахо", "пособия", "няня",
        "поликлиника", "русскоговорящий врач", "працюю", "шукаю"
    ]
}

# Запрещённые слова (отсеиваем тех, кто предлагает услуги/вакансии)
STOP_WORDS = [
    "ищем", "требуется", "вакансия", "набираем", "предлагаем", "услуги", "помогу",
    "пробив", "фнс", "оформлю", "сниму", "сдаю", "аренда от", "работа для девушек"
]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ====================== БАЗА ДАННЫХ ======================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, status TEXT, first_contact TIMESTAMP)')
    conn.close()

def get_status(user_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT status FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row[0] if row else None

def set_status(user_id, status):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR REPLACE INTO users (user_id, status, first_contact) VALUES (?, ?, ?)",
                 (user_id, status, datetime.now()))
    conn.commit()
    conn.close()

# ====================== ИИ ======================
async def ai_check(text, mode="is_lead"):
    try:
        if mode == "is_lead":
            prompt = "Ты HR-аналитик. Ответь ТОЛЬКО ДА или НЕТ. ДА — если человек имеет проблему и ищет решение (жильё, работа, документы, медицина и т.д.). НЕТ — если это вакансия, реклама услуг или спам."
        else:
            prompt = "Человек проявил интерес к твоему предложению? Ответь ДА или НЕТ."

        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": text}],
            max_tokens=5,
            temperature=0
        )
        return "ДА" in res.choices[0].message.content.upper()
    except Exception as e:
        log(f"Ошибка ИИ: {e}")
        return False

# ====================== ОБРАБОТЧИК ======================
init_db()
client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    if not event.sender_id or getattr(event.sender, 'bot', False):
        return

    uid = event.sender_id
    text = event.raw_text.lower().strip()

    # === ЛИЧНЫЕ СООБЩЕНИЯ ===
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
                    await client.send_message(REPORT_CHAT_ID, f"🔥 ЛИД ДОЖАТ!\nID: {uid}")
        return

    # === ГРУППЫ ===
    if not event.is_group:
        return
    if (datetime.now(timezone.utc) - event.date).total_seconds() > 600:
        return

    # Проверка на стоп-слова
    if any(word in text for word in STOP_WORDS):
        return

    # Проверка на триггер-слова
    has_trigger = any(word in text for category in TRIGGER_WORDS.values() for word in category)

    if has_trigger and get_status(uid) is None:
        if await ai_check(text, "is_lead"):
            try:
                chat = await event.get_chat()
                username = f"@{event.sender.username}" if event.sender.username else f"ID:{uid}"
                msg_link = f"https://t.me/c/{str(event.chat_id)[4:]}/{event.id}"

                report = (
                    f"🎯 **НОВЫЙ ЛИД**\n"
                    f"👤 {event.sender.first_name} ({username})\n"
                    f"🏠 Группа: {chat.title}\n"
                    f"💬 {event.raw_text[:200]}\n"
                    f"🔗 [Сообщение]({msg_link})"
                )

                await client.send_message(REPORT_CHAT_ID, report, link_preview=False)

                set_status(uid, "sent")
                await asyncio.sleep(random.randint(45, 120))

                first_msg = random.choice([
                    "Здравствуйте! Видела ваше сообщение. Подскажите, вы сейчас решаете вопрос с жильём/работой/документами?",
                    "Добрый день! Заметила, что у вас проблема с переездом/жильём. Могу подсказать варианты, если интересно."
                ])

                await client.send_message(uid, first_msg)
                log(f"✅ Отправили первое сообщение пользователю {uid}")

            except Exception as e:
                log(f"Ошибка при работе с лидом {uid}: {e}")

# ====================== ЗАПУСК ======================
async def main():
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.getenv("PORT", 8080))), 
                     type('Handler', (BaseHTTPRequestHandler,), {'do_GET': lambda s: (s.send_response(200), s.end_headers(), s.wfile.write(b"OK"))})).serve_forever(), 
                     daemon=True).start()

    await client.start()
    log("🚀 Бот запущен — Lead Generator v2 (триггерный поиск)")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
