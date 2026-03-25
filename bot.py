import asyncio
import random
import os
from datetime import datetime, timezone
from telethon import TelegramClient, events
from openai import AsyncOpenAI

# --- [КОНФИГУРАЦИЯ] ---
API_ID = 35523804          
API_HASH = 'ff7673ebc0e925a32fb52693bdfae16f'     
SESSION_NAME = 'hr_assistant_session'
REPORT_CHAT_ID = 7238685565 
RECRUITER_TAG = "@hannaober"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# СЛОВАРЬ ДЛЯ СТАТУСОВ (в памяти)
user_db = {} 

# СПИСОК СТОП-ФРАЗ (КТО ПРЕДЛАГАЕТ РАБОТУ)
STOP_PHRASES = [
    'ищем', 'вакансия', 'в офис', 'на склад', 'требуются', 'набираем', 
    '18-35', '18-40', 'зарплата от', 'оплата от', 'упаковке', 'сортировке',
    'подробности в лс', 'пишите @', 'на прямую', 'официальное'
]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# --- [ЛОГИКА ИИ] ---
async def ai_is_interested(text):
    try:
        response = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Если человек проявил интерес к работе (да, подробнее, ок), ответь ДА. Иначе НЕТ."},
                {"role": "user", "content": text}
            ],
            max_tokens=5
        )
        return "ДА" in response.choices[0].message.content.upper()
    except: return True

async def ai_is_seeker(text):
    # ПРОВЕРКА НА СТОП-СЛОВА (Чтобы не путать с вакансиями)
    t = text.lower()
    if any(phrase in t for phrase in STOP_PHRASES):
        return False
        
    try:
        response = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ты HR. Ответь ДА только если человек пишет 'Я ищу работу' или 'Нужна подработка'. Если это объявление о найме или вакансия — ответь НЕТ."},
                {"role": "user", "content": text}
            ],
            max_tokens=5
        )
        return "ДА" in response.choices[0].message.content.upper()
    except: return False

# --- [ОСНОВНОЙ КЛИЕНТ] ---
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    if not event.sender or event.sender.bot: return
    user_id = event.sender_id

    # А) ЛИЧКА (ДИАЛОГ)
    if event.is_private:
        status = user_db.get(user_id)
        if status == "sent":
            if await ai_is_interested(event.raw_text):
                await event.reply("Условия: удаленно, 2000€ + 2%, крипто-сфера. Обучение есть. Вам подходит?")
                user_db[user_id] = "offered"
        elif status == "offered":
            if await ai_is_interested(event.raw_text):
                await event.reply(f"Отлично! Напишите куратору Ханне: {RECRUITER_TAG}")
                user_db[user_id] = "final"

    # Б) ГРУППЫ (ПОИСК)
    elif event.is_group:
        # Проверка: сообщение свежее (не старее 2 минут)
        if (datetime.now(timezone.utc) - event.date).total_seconds() > 120: return
        
        if await ai_is_seeker(event.raw_text):
            if user_id not in user_db:
                log(f"Нашел соискателя: {user_id}")
                await client.send_message(REPORT_CHAT_ID, f"🔎 **ЛИД:** {event.sender.first_name}\n📝: {event.raw_text[:80]}")
                
                # Пауза перед тем как написать человеку
                await asyncio.sleep(20)
                try:
                    await client.send_message(user_id, "Здравствуйте! Увидела ваш запрос в группе. У нас есть удаленная вакансия (крипто-сфера, без опыта). Интересно узнать детали?")
                    user_db[user_id] = "sent"
                except: pass

async def main():
    await client.start()
    log("🚀 БОТ ЗАПУЩЕН")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
