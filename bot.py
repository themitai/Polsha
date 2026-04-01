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
DB_PATH = "leads_v3.db"

# ====================== РАСШИРЕННЫЕ ТРИГГЕРЫ ======================
TRIGGERS = {
    "переезд": [
        "приехал сегодня", "очередь на границе", "пеший переход", "еду в польшу", "выезжаю из",
        "карта побыту", "мельдунок", "pesel", "подача на карту", "виза закончилась", "освядчение",
        "karta pobytu", "meldunek"
    ],
    "жилье": [
        "ищу жилье", "сниму квартиру", "нужна комната", "ищу кавалерку", "жилье посуточно",
        "зніму квартиру", "шукаю житло", "mieszkanie", "kawalerka", "pokój"
    ],
    "работа": [
        "ищу работу", "шукаю роботу", "подработка", "підробіток", "работа без языка",
        "работа водителем", "код 95", "тахограф"
    ],
    "медицина": [
        "детский сад", "садик", "школа для ребенка", "800+", "dobry start", "przedszkole",
        "русскоговорящий врач", "поликлиника", "няня"
    ]
}

STOP_WORDS = ["ищем", "требуется", "вакансия", "набираем", "предлагаем", "услуги", "помогу", "пробив"]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ====================== БАЗА ДАННЫХ ======================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS leads 
                    (user_id INTEGER PRIMARY KEY, status TEXT, category TEXT, first_contact TEXT)''')
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
        conn.execute("INSERT OR REPLACE INTO leads (user_id, status, category, first_contact) VALUES (?, ?, ?, ?)",
                     (user_id, status, category, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except:
        pass

# ====================== ИИ ======================
async def ai_check(text, mode="is_lead"):
    if not ai_client:
        return True
    try:
        if mode == "is_lead":
            prompt = "Ответь ТОЛЬКО ДА или НЕТ. ДА — если человек ищет помощь по жилью, работе, документам, переезду или медицине."
        else:
            prompt = "Человек заинтересован в предложении? Ответь ДА или НЕТ."

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

# ====================== ПЕРВЫЕ СООБЩЕНИЯ ======================
FIRST_MESSAGES = {
    "переезд": [
        "Здравствуйте! Видела, что у вас вопрос с переездом или документами. Могу подсказать полезную информацию.",
        "Добрый день! Заметила сообщение про границу/документы. Есть ли у вас уже карта побыту или pesel?"
    ],
    "жилье": [
        "Здравствуйте! Вы ищете жильё? Подскажите, какой район и на какой срок интересует?",
        "Добрый день! Видела, что вы ищете квартиру или комнату. Могу помочь с вариантами."
    ],
    "работа": [
        "Здравствуйте! Вы ищете работу? Подскажите, в какой сфере и с каким опытом?",
        "Добрый день! Заметила, что вы ищете подработку или основную работу."
    ],
    "медицина": [
        "Здравствуйте! У вас вопрос с медициной или садиком для ребёнка?",
        "Добрый день! Нужна помощь с поиском врача или детского сада?"
    ],
    "default": [
        "Здравствуйте! Видела ваше сообщение. У вас сейчас какая-то проблема или вопрос?",
        "Добрый день! Чем могу помочь?"
    ]
}

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

    # Личные сообщения
    if event.is_private:
        status = get_status(uid)
        if status in ("sent", "offered"):
            log(f"📩 ЛС от {uid} | статус={status}")
            if await ai_check(text, "is_interest"):
                if status == "sent":
                    await event.reply("💼 У нас есть удалённая позиция в крипто-сфере. ЗП 2000€ + %. Подходит?")
                    set_status(uid, "offered")
                elif status == "offered":
                    await event.reply(f"Отлично! Напишите куратору: {RECRUITER_TAG}")
                    set_status(uid, "final")
        return

    # Группы
    if not event.is_group:
        return
    if (datetime.now(timezone.utc) - event.date).total_seconds() > 600:
        return

    if any(word in text_lower for word in STOP_WORDS):
        return

    # Определяем категорию
    category = "default"
    for cat, words in TRIGGERS.items():
        if any(word in text_lower for word in words):
            category = cat
            break

    if category != "default" and get_status(uid) is None:
        if await ai_check(text, "is_lead"):
            try:
                chat = await event.get_chat()
                username = f"@{event.sender.username}" if event.sender.username else f"ID:{uid}"
                msg_link = f"https://t.me/c/{str(event.chat_id)[4:]}/{event.id}"

                report = (
                    f"🎯 **ЛИД | {category.upper()}**\n"
                    f"👤 {event.sender.first_name or '—'} ({username})\n"
                    f"🏠 Группа: {chat.title}\n"
                    f"💬 {text[:180]}\n"
                    f"🔗 [Ссылка]({msg_link})"
                )

                await client.send_message(REPORT_CHAT_ID, report, link_preview=False)

                set_status(uid, "sent", category)

                await asyncio.sleep(random.randint(60, 180))

                first_msg = random.choice(FIRST_MESSAGES.get(category, FIRST_MESSAGES["default"]))
                await client.send_message(uid, first_msg)

                log(f"✅ Отправлено сообщение ({category}) пользователю {uid}")

            except Exception as e:
                log(f"❌ Ошибка обработки лида {uid}: {e}")

# ====================== ЗАПУСК ======================
async def main():
    def health_server():
        port = int(os.getenv("PORT", 8080))
        server = HTTPServer(('0.0.0.0', port),
            type('H', (BaseHTTPRequestHandler,), {'do_GET': lambda s: (s.send_response(200), s.end_headers(), s.wfile.write(b"OK"))}))
        server.serve_forever()
    threading.Thread(target=health_server, daemon=True).start()

    await client.start()
    me = await client.get_me()
    log(f"🚀 Бот запущен на аккаунте: {me.first_name} (@{me.username or '—'})")
    log("🎯 Режим: Продвинутый Lead Generator v3 (с категориями)")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
