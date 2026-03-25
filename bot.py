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

# База в памяти (чтобы не тупил)
user_db = {} 

# РАСШИРЕННЫЙ СПИСОК МИНУС-СЛОВ (Для отсева услуг и вакансий)
STOP_PHRASES = [
    'ищем', 'вакансия', 'в офис', 'на склад', 'требуются', 'набираем', 
    'услуги', 'фнс', 'снимаем', 'выполняю', 'пробив', 'помогу с', 
    'оплата от', 'лс', 'запись', 'модели', 'тату', 'клиентов'
]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# --- [ЛОГИКА ИИ] ---
async def ai_check(text, task="is_seeker"):
    prompts = {
        "is_seeker": (
            "Твоя задача — найти только тех, кто ХОЧЕТ УСТРОИТЬСЯ на работу (соискателей). "
            "Если человек ПРЕДЛАГАЕТ услуги (ФНС, помощь, оформление, ремонт, тату) — ответь НЕТ. "
            "Если человек ПРЕДЛАГАЕТ вакансию (ищем, требуется) — ответь НЕТ. "
            "Если человек пишет 'Я ищу работу', 'Ищу подработку', 'Нужен ворк' — ответь ДА. "
            "Отвечай только ДА или НЕТ."
        ),
        "is_interested": "Человек проявил интерес к вакансии? Ответь только ДА или НЕТ."
    }
    try:
        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompts[task]}, {"role": "user", "content": text}],
            max_tokens=5, temperature=0
        )
        return "ДА" in res.choices[0].message.content.upper()
    except: return False

# --- [КЛИЕНТ] ---
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    if not event.sender or event.sender.bot: return
    user_id = event.sender_id

    # А) ДИАЛОГ В ЛИЧКЕ
    if event.is_private:
        status = user_db.get(user_id)
        if status:
            log(f"Ответ от кандидата {user_id}: {event.raw_text}")
            if await ai_check(event.raw_text, "is_interested"):
                if status == "sent":
                    await event.reply("Условия: удаленно, крипто-направление. ЗП: 2000€ + 2%. Обучение 2 дня. Подходит?")
                    user_db[user_id] = "offered"
                elif status == "offered":
                    await event.reply(f"Супер! Пишите куратору Ханне, она даст доступ к обучению: {RECRUITER_TAG}")
                    user_db[user_id] = "final"
                    await client.send_message(REPORT_CHAT_ID, f"🔥 **ЛИД ДОЖАТ:** @{event.sender.username or user_id}")

    # Б) МОНИТОРИНГ ГРУПП
    elif event.is_group:
        # Проверяем только свежие сообщения
        if (datetime.now(timezone.utc) - event.date).total_seconds() > 120: return
        
        text_lower = event.raw_text.lower()
        if any(p in text_lower for p in STOP_PHRASES):
            return # Сразу скипаем услуги ФНС и прочее

        if await ai_check(event.raw_text, "is_seeker"):
            if user_id not in user_db:
                chat = await event.get_chat()
                msg_link = f"https://t.me/c/{str(event.chat_id)[4:]}/{event.id}" if not chat.username else f"https://t.me/{chat.username}/{event.id}"
                
                # Подробный отчет
                report = (
                    f"🎯 **ЛИД НАЙДЕН**\n"
                    f"👤 **Имя:** {event.sender.first_name}\n"
                    f"🆔 **ID:** `{user_id}`\n"
                    f"💬 **Текст:** {event.raw_text[:120]}\n"
                    f"📍 **Группа:** {chat.title}\n"
                    f"🔗 **Ссылка:** [ПЕРЕЙТИ]({msg_link})"
                )
                await client.send_message(REPORT_CHAT_ID, report, link_preview=False)
                
                # Пишем человеку через паузу
                user_db[user_id] = "sent"
                await asyncio.sleep(random.randint(15, 30))
                try:
                    await client.send_message(user_id, "Здравствуйте! Увидела ваш запрос в группе. У нас сейчас открыта удаленная позиция (крипто-сфера, без опыта). Вам интересно узнать детали?")
                except:
                    log(f"ЛС закрыты у {user_id}")

async def main():
    await client.start()
    log("🚀 БОТ ЗАПУЩЕН С ФИЛЬТРОМ УСЛУГ")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
