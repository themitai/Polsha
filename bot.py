import asyncio
import random
import os
import sqlite3
import sys
from datetime import datetime, timezone
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from openai import AsyncOpenAI

# --- [КОНФИГУРАЦИЯ] ---
API_ID = 35523804          
API_HASH = 'ff7673ebc0e925a32fb52693bdfae16f'
REPORT_CHAT_ID = 7238685565 
RECRUITER_TAG = "@hannaober"

# Берем данные из переменных Railway
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SESSION_STR = os.getenv("TELEGRAM_SESSION")

ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# Путь к базе данных (с учетом Volume на Railway)
DB_PATH = '/app/data/bot_data.db' if os.path.exists('/app/data') else 'bot_data.db'

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# --- [РАБОТА С БАЗОЙ SQLITE] ---
def init_db():
    if os.path.dirname(DB_PATH):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, status TEXT)''')
    conn.commit()
    conn.close()

def get_status(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM users WHERE user_id=?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except: return None

def set_status(user_id, status):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO users (user_id, status) VALUES (?, ?)", (user_id, status))
        conn.commit()
        conn.close()
    except Exception as e:
        log(f"Ошибка БД: {e}")

# --- [ЛОГИКА ИИ] ---
async def ai_check(text, mode="is_seeker"):
    # ТЕХНИЧЕСКИЙ ФИЛЬТР (отсекаем мусор сразу)
    STOP_LIST = ['ищем', 'вакансия', 'в офис', 'на склад', 'требуются', 'набираем', 'фнс', 'выполняю', 'услуги', 'пробив']
    t_lower = text.lower()
    if mode == "is_seeker":
        if any(s in t_lower for s in STOP_LIST) or len(text) > 500:
            return False

    prompts = {
        "is_seeker": (
            "Ты HR-фильтр. Ответь ДА, если человек ИЩЕТ работу или подработку. "
            "Ответь НЕТ, если это объявление о найме (предложение работы) или реклама услуг."
        ),
        "is_interest": "Человек проявил интерес к вакансии (да, ок, расскажите, интересно)? Ответь ДА или НЕТ."
    }
    try:
        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompts[mode]}, {"role": "user", "content": text}],
            max_tokens=5, temperature=0
        )
        return "ДА" in res.choices[0].message.content.upper()
    except Exception as e:
        log(f"Ошибка OpenAI: {e}")
        return False

# --- [ОСНОВНОЙ КЛИЕНТ] ---
if not SESSION_STR:
    log("КРИТИЧЕСКАЯ ОШИБКА: Переменная TELEGRAM_SESSION не найдена!")
    sys.exit(1)

init_db()
client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    # Лог любого входящего события (для отладки)
    chat_type = "ЛС" if event.is_private else "Группа"
    # log(f"📩 Вижу сообщение в {chat_type} (ID: {event.chat_id})")

    if not event.sender or event.sender.bot: return
    user_id = event.sender_id

    # 1. ДИАЛОГ В ЛИЧКЕ
    if event.is_private:
        status = get_status(user_id)
        log(f"👤 Сообщение в ЛС от {user_id}. Текст: {event.raw_text[:40]}. Статус: {status}")
        
        if status == "sent":
            if await ai_check(event.raw_text, "is_interest"):
                await asyncio.sleep(2)
                await event.reply(
                    "💼 **Детали вакансии:**\n"
                    "• Удаленно, крипто-сфера (обработка заявок).\n"
                    "• ЗП: 2000€/мес + 2% бонус.\n"
                    "• Обучение 2 дня (бесплатно).\n\n"
                    "Вам подходит такой формат?"
                )
                set_status(user_id, "offered")
        
        elif status == "offered":
            if await ai_check(event.raw_text, "is_interest"):
                await asyncio.sleep(2)
                await event.reply(f"Прекрасно! Для начала обучения напишите нашему куратору Ханне: {RECRUITER_TAG}")
                set_status(user_id, "final")
                await client.send_message(REPORT_CHAT_ID, f"🔥 **ЛИД ДОЖАТ!** Кандидат: @{event.sender.username or user_id}")

    # 2. МОНИТОРИНГ ГРУПП
    elif event.is_group:
        # Игнорируем старые сообщения (более 3 минут)
        if (datetime.now(timezone.utc) - event.date).total_seconds() > 180: return
        
        if await ai_check(event.raw_text, "is_seeker"):
            if get_status(user_id) is None:
                log(f"✅ НАЙДЕН ЛИД: {user_id}")
                chat = await event.get_chat()
                
                # Генерация ссылки (учитываем Topics)
                msg_id = event.id
                if chat.username:
                    msg_link = f"https://t.me/{chat.username}/{msg_id}"
                else:
                    msg_link = f"https://t.me/c/{str(event.chat_id)[4:]}/{msg_id}"

                # Отчет в твой канал
                report = (
                    f"🎯 **ЛИД НАЙДЕН**\n"
                    f"👤 **Имя:** {event.sender.first_name}\n"
                    f"🆔 **ID:** `{user_id}`\n"
                    f"💬 **Текст:** {event.raw_text[:150]}\n"
                    f"📍 **Группа:** {chat.title}\n"
                    f"🔗 **Ссылка:** [ПЕРЕЙТИ]({msg_link})"
                )
                await client.send_message(REPORT_CHAT_ID, report, link_preview=False)
                
                # Записываем в базу и пишем в ЛС через паузу
                set_status(user_id, "sent")
                await asyncio.sleep(random.randint(20, 40))
                try:
                    await client.send_message(user_id, "Здравствуйте! Увидела ваш запрос в группе. У нас сейчас открыта удаленная позиция (крипто-сфера, без опыта). Вам интересно узнать детали?")
                    log(f"✉️ Приветствие отправлено юзеру {user_id}")
                except Exception as e:
                    log(f"❌ Не удалось написать в ЛС: {e}")

async def main():
    await client.start()
    log("🚀 БОТ ЗАПУЩЕН И ГОТОВ К РАБОТЕ")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
