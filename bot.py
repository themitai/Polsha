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

# API ключ OpenAI из переменных Railway
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

DB_FILE = "sent_users.txt"
KNOWN_CHATS_FILE = "known_chats.txt"

# --- [ФИЛЬТРЫ ТРИГГЕРОВ] ---

# ЖЕСТКИЕ МИНУС-СЛОВА (если есть хоть одно из них — бот игнорирует сообщение сразу)
HARD_STOP_WORDS = [
    'требуется', 'ищем', 'вакансия', 'набираю', 'в команду', 'оплата от', 
    'зарплата', 'ищу сотрудника', 'ищу персонал', 'лс', 'пишите в директ',
    'ищем моделей', 'нужны модели', 'ищу модель', 'тату', 'tattoo', 'маникюр',
    'ресницы', 'брови', 'запись в лс', 'приглашаем', 'набор', 'вакансии'
]

# ТЕКСТ ВАКАНСИИ ДЛЯ КАНДИДАТА
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
    # 1. Предварительная проверка на стоп-слова (экономим бюджет)
    text_lower = text.lower()
    if stage == "find_seeker":
        if any(stop in text_lower for stop in HARD_STOP_WORDS):
            return False

    # 2. Инструкции для ИИ
    prompts = {
        "find_seeker": (
            "Ты — строгий HR-фильтр. Твоя цель: найти людей, которые ХОТЯТ УСТРОИТЬСЯ на работу. "
            "ОТВЕТЬ 'НЕТ', ЕСЛИ: это мастер ищет клиентов (тату, модели, услуги) или работодатель ищет людей. "
            "ОТВЕТЬ 'ДА', ТОЛЬКО ЕСЛИ: человек сам пишет 'Ищу работу', 'Нужна подработка', 'Ищу ворк'. "
            "Важно: Фраза 'Ищу моделей' — это НЕТ. Фраза 'Ищу работу' — это ДА."
        ),
        "check_interest": (
            "Если человек проявил интерес к вакансии (сказал 'да', 'расскажите', 'подходит', 'что за работа'), ответь 'ДА'. "
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
    except Exception as e:
        print(f"Ошибка ИИ: {e}")
        return False

# --- [БАЗА ДАННЫХ] ---

def check_db(user_id, status):
    if not os.path.exists(DB_FILE): return False
    with open(DB_FILE, "r") as f:
        return f"{user_id}:{status}" in f.read()

def update_db(user_id, status):
    with open(DB_FILE, "a") as f:
        f.write(f"{user_id}:{status}\n")

# --- [РАБОТА КЛИЕНТА] ---

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    # А) МОНИТОРИНГ ГРУПП
    if event.is_group:
        if (datetime.now(timezone.utc) - event.date).total_seconds() > 60: return
        if not event.sender or event.sender.bot: return

        # Запоминаем чат (тихо)
        if not os.path.exists(KNOWN_CHATS_FILE): open(KNOWN_CHATS_FILE, "w").close()
        with open(KNOWN_CHATS_FILE, "a+") as f:
            f.seek(0)
            if str(event.chat_id) not in f.read():
                f.write(f"{event.chat_id}\n")

        # Анализ сообщения на поиск работы
        if await ai_analyze(event.raw_text, stage="find_seeker"):
            if not check_db(event.sender_id, "sent"):
                user_link = f"tg://user?id={event.sender_id}"
                await client.send_message(REPORT_CHAT_ID, f"🔎 **ИИ НАШЕЛ СОИСКАТЕЛЯ**\n👤: {event.sender.first_name}\n📝: {event.raw_text[:120]}\n👉 [ОТКРЫТЬ]({user_link})")
                
                # Пауза перед первым сообщением (5-12 минут)
                await asyncio.sleep(random.randint(300, 720))
                try:
                    await client.send_message(event.sender_id, "Здравствуйте! Увидела ваше сообщение в группе. У нас сейчас открыта удаленная позиция (крипто-направлении, без опыта). Вам было бы интересно узнать детали?")
                    update_db(event.sender_id, "sent")
                except:
                    await client.send_message(REPORT_CHAT_ID, f"❌ У `{event.sender_id}` закрыты ЛС.")

    # Б) ОБРАБОТКА ЛИЧКИ (ДИАЛОГ)
    elif event.is_private:
        if not event.sender or event.sender.bot: return
        
        # Шаг 1: Человек ответил на приветствие
        if check_db(event.sender_id, "sent") and not check_db(event.sender_id, "offered"):
            if await ai_analyze(event.raw_text, stage="check_interest"):
                await asyncio.sleep(random.randint(40, 80))
                await event.reply(VACANCY_TEXT)
                update_db(event.sender_id, "offered")
        
        # Шаг 2: Человек согласился после оффера
        elif check_db(event.sender_id, "offered") and not check_db(event.sender_id, "final"):
            if await ai_analyze(event.raw_text, stage="check_interest"):
                await asyncio.sleep(random.randint(40, 80))
                final_msg = f"Прекрасно! Для записи на обучение напишите куратору Ханне: {RECRUITER_TAG}\nОна ждет вашего сообщения и введет в курс дела!"
                await event.reply(final_msg)
                update_db(event.sender_id, "final")
                await client.send_message(REPORT_CHAT_ID, f"🔥 **ГОРЯЧИЙ ЛИД ПЕРЕДАН!**\nКандидат [id:{event.sender_id}](tg://user?id={event.sender_id}) пошел к Ханне.")

async def main():
    await client.start()
    
    # Синхронизация старых чатов при старте
    async for dialog in client.iter_dialogs():
        if dialog.is_group:
            with open(KNOWN_CHATS_FILE, "a+") as f:
                f.seek(0)
                if str(dialog.id) not in f.read():
                    f.write(f"{dialog.id}\n")
                    
    print("🚀 HR-Бот запущен. Работаем строго по соискателям!")
    await client.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
