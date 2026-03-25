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

# Ключ OpenAI из Variables Railway
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

DB_FILE = "sent_users.txt"
KNOWN_CHATS_FILE = "known_chats.txt"

# --- [ТЕКСТЫ ВАКАНСИИ] ---

SHORT_OFFER = (
    "У нас открыта удаленная позиция в крипто-направлении (можно без опыта).\n\n"
    "**Суть работы:** Обработка типовых заявок (перевод/конвертация) по пошаговой инструкции. "
    "Задачи понятные и повторяемые. Сначала проходите обучение с наставником.\n\n"
    "**Оплата:** 2000€ в месяц + 2% от объема.\n\n"
    "Вам подходит такой формат? Рассказать, как связаться с куратором?"
)

# --- [ЛОГИКА ИИ] ---

async def ai_analyze(text, stage="find_seeker"):
    """
    stage "find_seeker": ищет ли человек работу (соискатель).
    stage "check_interest": интересен ли человеку оффер.
    """
    prompts = {
        "find_seeker": (
            "Ты — ассистент HR. Проверь сообщение. Если человек сам ИЩЕТ работу или подработку, ответь 'ДА'. "
            "Если это реклама вакансии от другого HR (слова 'требуется', 'ищем', 'набираю', 'оплата от') — ответь 'НЕТ'. "
            "Ищи только запросы соискателей."
        ),
        "check_interest": (
            "Если человек после описания вакансии подтвердил интерес (сказал 'да', 'подходит', 'хочу', 'давайте контакты'), ответь 'ДА'. "
            "В остальных случаях 'НЕТ'."
        )
    }
    
    try:
        response = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompts[stage]}, {"role": "user", "content": text}],
            max_tokens=5, temperature=0
        )
        return "ДА" in response.choices[0].message.content.strip().upper()
    except: return False

# --- [ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ] ---

def check_db(user_id, status="sent"):
    # status 'sent' - написали первый раз, 'offered' - дали описание
    if not os.path.exists(DB_FILE): return False
    with open(DB_FILE, "r") as f:
        return f"{user_id}:{status}" in f.read()

def update_db(user_id, status):
    with open(DB_FILE, "a") as f:
        f.write(f"{user_id}:{status}\n")

# --- [ОСНОВНОЙ КЛИЕНТ] ---

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    # 1. МОНИТОРИНГ ГРУПП
    if event.is_group:
        if (datetime.now(timezone.utc) - event.date).total_seconds() > 60: return
        if not event.sender or event.sender.bot: return

        # Тихая запись чата
        if not os.path.exists(KNOWN_CHATS_FILE): open(KNOWN_CHATS_FILE, "w").close()
        with open(KNOWN_CHATS_FILE, "a+") as f:
            f.seek(0)
            if str(event.chat_id) not in f.read():
                f.write(f"{event.chat_id}\n")

        # Ищем соискателя
        if await ai_analyze(event.raw_text, stage="find_seeker"):
            if not check_db(event.sender_id, "sent"):
                user_link = f"tg://user?id={event.sender_id}"
                await client.send_message(REPORT_CHAT_ID, f"🔎 **ИИ НАШЕЛ СОИСКАТЕЛЯ**\n👤: {event.sender.first_name}\n📝: {event.raw_text[:100]}\n👉 [ОТКРЫТЬ]({user_link})")
                
                await asyncio.sleep(random.randint(300, 600))
                try:
                    await client.send_message(event.sender_id, "Здравствуйте! Увидела ваше сообщение в группе. У нас сейчас открыта удаленная позиция (крипто-сфера, без опыта). Вам было бы интересно узнать детали?")
                    update_db(event.sender_id, "sent")
                except: pass

    # 2. ОБРАБОТКА ЛИЧКИ
    elif event.is_private:
        if not event.sender or event.sender.bot: return
        
        # Если мы уже написали приветствие, но еще не дали оффер
        if check_db(event.sender_id, "sent") and not check_db(event.sender_id, "offered"):
            # Проверяем, ответил ли "Да" на первый вопрос
            if await ai_analyze(event.raw_text, stage="check_interest"):
                await asyncio.sleep(random.randint(30, 60))
                await event.reply(SHORT_OFFER)
                update_db(event.sender_id, "offered")
        
        # Если дали оффер и человек согласен связаться
        elif check_db(event.sender_id, "offered") and not check_db(event.sender_id, "final"):
            if await ai_analyze(event.raw_text, stage="check_interest"):
                await asyncio.sleep(random.randint(30, 60))
                final_msg = f"Прекрасно! Для записи на вводное обучение напишите нашему куратору Ханне: {RECRUITER_TAG}\nОна введет вас в курс дела. Ждем вас в команде!"
                await event.reply(final_msg)
                update_db(event.sender_id, "final")
                await client.send_message(REPORT_CHAT_ID, f"🔥 **ГОРЯЧИЙ ЛИД!**\nКандидат [id:{event.sender_id}](tg://user?id={event.sender_id}) отправлен к Ханне.")

async def main():
    await client.start()
    
    # Инициализация списка чатов
    async for dialog in client.iter_dialogs():
        if dialog.is_group:
            with open(KNOWN_CHATS_FILE, "a+") as f:
                f.seek(0)
                if str(dialog.id) not in f.read():
                    f.write(f"{dialog.id}\n")
                    
    print("🚀 HR-Ассистент запущен!")
    await client.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
