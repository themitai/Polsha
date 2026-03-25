import asyncio
import random
import os
import sqlite3
import sys
from datetime import datetime, timezone
from telethon import TelegramClient, events
from openai import AsyncOpenAI

# --- [КОНФИГУРАЦИЯ] ---
API_ID = 35523804          
API_HASH = 'ff7673ebc0e925a32fb52693bdfae16f'     
SESSION_NAME = 'hr_session'
REPORT_CHAT_ID = 7238685565 
RECRUITER_TAG = "@hannaober"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# Путь к базе данных (настроен под Railway Volume)
DB_PATH = '/app/data/bot_data.db' if os.path.exists('/app/data') else 'bot_data.db'

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# --- [БАЗА ДАННЫХ] ---
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
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def set_status(user_id, status):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO users (user_id, status) VALUES (?, ?)", (user_id, status))
    conn.commit()
    conn.close()

# --- [ЛОГИКА ФИЛЬТРАЦИИ И ИИ] ---

async def ai_check(text, mode="is_seeker"):
    # ТЕХНИЧЕСКИЙ ФИЛЬТР (отсекаем мусор сразу)
    STOP_LIST = [
        'ищем', 'вакансия', 'в офис', 'на склад', 'требуются', 'набираем', 
        'услуги', 'фнс', 'выполняю', 'пробив', 'помогу', 'оформлю', 'запись', 'тату'
    ]
    t_lower = text.lower()
    if mode == "is_seeker":
        if any(s in t_lower for s in STOP_LIST) or len(text) > 450:
            return False

    prompts = {
        "is_seeker": (
            "Ты — HR. Проанализируй сообщение. Твоя задача найти только СОИСКАТЕЛЯ. "
            "Если человек пишет 'Ищу работу', 'Нужна подработка', 'Хочу ворк' — ответь ДА. "
            "Если человек ПРЕДЛАГАЕТ работу (вакансия, ищем) или УСЛУГИ (сделаю, помогу, ФНС) — ответь НЕТ. "
            "Отвечай только ДА или НЕТ."
        ),
        "is_interest": "Человек проявил интерес к вакансии (сказал: да, подробнее, ок, хочу)? Ответь только ДА или НЕТ."
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
init_db()
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    if not event.sender or event.sender.bot: return
    user_id = event.sender_id

    # 1. ОБЩЕНИЕ В ЛИЧКЕ (ДИАЛОГ)
    if event.is_private:
        status = get_status(user_id)
        if not status: return

        log(f"Входящее в ЛС от {user_id}. Текст: {event.raw_text[:50]}")
        
        if status == "sent":
            if await ai_check(event.raw_text, "is_interest"):
                await asyncio.sleep(2)
                await event.reply(
                    "💼 **Условия работы:**\n"
                    "• Удаленно (крипто-направление).\n"
                    "• Задачи: обработка заявок по инструкции.\n"
                    "• ЗП: 2000€ в месяц + 2% бонус.\n"
                    "• Обучение 2 дня (бесплатно).\n\n"
                    "Вам подходит такой формат?"
                )
                set_status(user_id, "offered")
        
        elif status == "offered":
            if await ai_check(event.raw_text, "is_interest"):
                await asyncio.sleep(2)
                await event.reply(f"Отлично! Для начала обучения напишите нашему куратору Ханне: {RECRUITER_TAG}")
                set_status(user_id, "final")
                await client.send_message(REPORT_CHAT_ID, f"🔥 **ЛИД ГОТОВ!** Кандидат: @{event.sender.username or user_id}")

    # 2. МОНИТОРИНГ ГРУПП
    elif event.is_group:
        # Проверяем только свежие (до 2 минут)
        if (datetime.now(timezone.utc) - event.date).total_seconds() > 120: return
        
        if await ai_check(event.raw_text, "is_seeker"):
            if get_status(user_id) is None:
                chat = await event.get_chat()
                msg_link = f"https://t.me/c/{str(event.chat_id)[4:]}/{event.id}" if not chat.username else f"https://t.me/{chat.username}/{event.id}"
                
                # Отправка отчета
                report = (
                    f"🎯 **ЛИД НАЙДЕН**\n"
                    f"👤 **Имя:** {event.sender.first_name}\n"
                    f"🆔 **ID:** `{user_id}`\n"
                    f"💬 **Текст:** {event.raw_text[:120]}\n"
                    f"📍 **Группа:** {chat.title}\n"
                    f"🔗 **Ссылка:** [ПЕРЕЙТИ]({msg_link})"
                )
                await client.send_message(REPORT_CHAT_ID, report, link_preview=False)
                
                # Пишем первое сообщение в ЛС
                set_status(user_id, "sent")
                await asyncio.sleep(random.randint(20, 45)) # Пауза для естественности
                try:
                    await client.send_message(user_id, "Здравствуйте! Увидела ваш запрос в группе. У нас сейчас открыта удаленная позиция (крипто-сфера, без опыта). Вам интересно узнать детали?")
                except Exception as e:
                    log(f"Не удалось написать {user_id}: {e}")

async def main():
    await client.start()
    log("🚀 БОТ ЗАПУЩЕН И МОНИТОРИТ ГРУППЫ")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
