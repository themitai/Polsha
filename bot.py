import asyncio
import random
import os
from datetime import datetime, timezone
from telethon import TelegramClient, events, types
from openai import AsyncOpenAI

# --- [КОНФИГУРАЦИЯ] ---
API_ID = 35523804          
API_HASH = 'ff7673ebc0e925a32fb52693bdfae16f'     
SESSION_NAME = 'hr_assistant_session'
REPORT_CHAT_ID = 7238685565 
RECRUITER_TAG = "@hannaober"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

DB_FILE = "sent_users.txt"
KNOWN_CHATS_FILE = "known_chats.txt"

HARD_STOP_WORDS = ['требуется', 'ищем', 'вакансия', 'набираю', 'оплата от', 'ищем моделей', 'тату', 'маникюр']

VACANCY_TEXT = (
    "Открыта удалённая позиция для кандидатов без опыта в крипто-направлении. "
    "Суть: обработка типовых заявок (перевод/конвертация) по пошаговой инструкции. "
    "Это отличный вариант для новичков — задачи понятные, обучение на старте с наставником.\n\n"
    "**Условия:**\n"
    "• Зарплата: 2000€ в месяц + 2% от объема.\n"
    "• График: удаленно, гибкие окна.\n\n"
    "Вам подходит такой формат? Рассказать, как связаться с куратором?"
)

# --- [ЛОГИКА ИИ] ---

async def ai_analyze(text, stage="find_seeker"):
    text_lower = text.lower()
    if stage == "find_seeker" and any(stop in text_lower for stop in HARD_STOP_WORDS):
        return False

    prompts = {
        "find_seeker": "Ты HR. Если человек ищет работу, ответь 'ДА'. Если предлагает услуги/вакансию — 'НЕТ'.",
        "check_interest": "Если человек проявил интерес (сказал да, подробнее, что за работа, ок, хочу), ответь 'ДА'. Иначе 'НЕТ'."
    }
    
    try:
        response = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompts[stage]}, {"role": "user", "content": text}],
            max_tokens=5, temperature=0
        )
        return "ДА" in response.choices[0].message.content.strip().upper()
    except Exception as e:
        print(f"Ошибка ИИ: {e}")
        return False

# --- [ФУНКЦИИ БАЗЫ] ---

def get_user_status(user_id):
    if not os.path.exists(DB_FILE): return None
    with open(DB_FILE, "r") as f:
        for line in f:
            if str(user_id) in line:
                return line.split(":")[-1].strip()
    return None

def update_user_status(user_id, status):
    lines = []
    found = False
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            for line in f:
                if str(user_id) in line:
                    lines.append(f"{user_id}:{status}\n")
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f"{user_id}:{status}\n")
    with open(DB_FILE, "w") as f:
        f.writelines(lines)

# --- [КЛИЕНТ] ---

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    if not event.sender or event.sender.bot: return

    # А) ГРУППЫ
    if event.is_group:
        if (datetime.now(timezone.utc) - event.date).total_seconds() > 60: return
        if await ai_analyze(event.raw_text, "find_seeker"):
            if get_user_status(event.sender_id) is None:
                user_link = f"tg://user?id={event.sender_id}"
                await client.send_message(REPORT_CHAT_ID, f"🔎 **ЛИД:** {event.sender.first_name}\n📝: {event.raw_text[:100]}\n👉 [ОТКРЫТЬ]({user_link})")
                
                await asyncio.sleep(random.randint(10, 20)) # Для теста уменьшил паузу
                try:
                    await client.send_message(event.sender_id, "Здравствуйте! Увидела ваше сообщение в группе. У нас сейчас открыта удаленная позиция (крипто-сфера, без опыта). Вам было бы интересно узнать детали?")
                    update_user_status(event.sender_id, "sent")
                except: pass

    # Б) ЛИЧКА
    elif event.is_private:
        status = get_user_status(event.sender_id)
        
        if status == "sent":
            if await ai_analyze(event.raw_text, "check_interest"):
                await asyncio.sleep(random.randint(5, 10))
                await event.reply(VACANCY_TEXT)
                update_user_status(event.sender_id, "offered")
        
        elif status == "offered":
            if await ai_analyze(event.raw_text, "check_interest"):
                await asyncio.sleep(random.randint(5, 10))
                await event.reply(f"Отлично! Для связи с куратором напишите Ханне: {RECRUITER_TAG}\nОна введет вас в курс дела!")
                update_user_status(event.sender_id, "final")
                await client.send_message(REPORT_CHAT_ID, f"🔥 **ЛИД ГОТОВ:** [id:{event.sender_id}](tg://user?id={event.sender_id})")

async def main():
    await client.start()
    print("🚀 Бот запущен и готов к тестам!")
    await client.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
