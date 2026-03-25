import asyncio
import random
import os
from datetime import datetime, timezone
from telethon import TelegramClient, events, types
from telethon.tl.functions.channels import JoinChannelRequest

# --- [БЛОК НАСТРОЕК] ---
API_ID = 35523804          
API_HASH = 'ff7673ebc0e925a32fb52693bdfae16f'     
SESSION_NAME = 'hr_assistant_session'

# ID твоего чата для отчетов
REPORT_CHAT_ID = 7238685565 

# Контакт рекрутера в тексте
RECRUITER_TAG = "@hannaober" 

# --- [ТЕКСТЫ] ---
FIRST_QUESTION = "Здравствуйте! Увидела ваш запрос в группе по поиску работы. У нас сейчас открыта позиция в криптовалютном направлении (удаленно, без опыта). Вам прислать подробности по задачам?"

DETAILED_OFFER = f"""
Открыта удалённая позиция для кандидатов без опыта в криптовалютном направлении. В работе — обработка типовых заявок внутри процесса команды.

**Что вы будете делать:**
* Получать заявки в рабочем канале и брать их в работу.
* Проверять наличие вводных данных.
* Выполнять операции по регламенту (перевод/конвертация).
* Доводить заявку до результата.

**Обучение:**
Сначала — вводное обучение. Далее — практика с наставником.

**Для начала обучения и связи с куратором напишите менеджеру:** {RECRUITER_TAG}
"""

# --- [ТРИГГЕРЫ] ---
KEYWORDS = [
    'ищу работу', 'ищу подработку', 'нужна работа', 'ищу вакансию', 
    'рассмотрю предложения', 'ищу удаленку', 'ищу удаленную', 
    'где найти работу', 'ищу работу без опыта', 'ищу заработок', 
    'хочу работать', 'ищу ворк', 'нужен ворк', 'ищу профит'
]

STOP_WORDS = [
    'требуется', 'ищем', 'вакансия', 'набираю', 'в команду', 
    'платим', 'зарплата', 'оплата', 'лс', 'пишите', 'подробности в',
    'обучаем', 'набор', 'ищу сотрудника', 'ищу персонал', 'ищу людей'
]

DB_FILE = "sent_users.txt"

# --- [ФУНКЦИИ БАЗЫ] ---
def is_already_sent(user_id):
    if not os.path.exists(DB_FILE): return False
    with open(DB_FILE, "r") as f:
        return str(user_id) in f.read().splitlines()

def mark_as_sent(user_id):
    with open(DB_FILE, "a") as f:
        f.write(f"{user_id}\n")

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# --- [ЛОГИКА БОТА] ---

# 1. ОТСЛЕЖИВАНИЕ ТВОИХ ВСТУПЛЕНИЙ (Когда ты сам зашел в чат)
@client.on(events.ChatAction)
async def action_handler(event):
    if event.user_joined or event.user_added:
        if event.user_id == (await client.get_me()).id:
            chat = await event.get_chat()
            await client.send_message(REPORT_CHAT_ID, f"🎯 **НОВАЯ ГРУППА:** Я начала мониторить чат «{chat.title}». Можно убирать его в архив!")

# 2. МОНИТОРИНГ СООБЩЕНИЙ В ГРУППАХ
@client.on(events.NewMessage)
async def group_handler(event):
    if event.is_group:
        # Проверка актуальности (сообщение не старше 1 минуты)
        if (datetime.now(timezone.utc) - event.date).total_seconds() > 60:
            return

        # Проверка на человека и не бота
        if not event.sender or not isinstance(event.sender, types.User) or event.sender.bot:
            return
        
        text = event.raw_text.lower()
        if len(text) > 250: return 
        
        if any(word in text for word in KEYWORDS) and not any(stop in text for stop in STOP_WORDS):
            sender = event.sender
            chat = await event.get_chat()
            
            if not is_already_sent(sender.id):
                user_link = f"tg://user?id={sender.id}"
                
                # Сразу шлем отчет тебе
                await client.send_message(REPORT_CHAT_ID, 
                    f"🔎 **КАНДИДАТ НАЙДЕН**\n👤: {sender.first_name}\n📍: {chat.title}\n📝: _{event.raw_text}_\n👉 [ОТКРЫТЬ ЧАТ]({user_link})")
                
                # Имитация человеческой паузы (3-10 минут)
                await asyncio.sleep(random.randint(180, 600))
                
                try:
                    await client.send_message(sender.id, FIRST_QUESTION)
                    mark_as_sent(sender.id)
                except:
                    await client.send_message(REPORT_CHAT_ID, f"❌ Не смогла написать `{sender.id}` (ЛС закрыты).")

# 3. АВТООТВЕТЧИК В ЛИЧКЕ
@client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def private_handler(event):
    if not event.sender or event.sender.bot: return
    
    text = event.raw_text.lower()
    positive_triggers = ['да', 'пришлите', 'интересно', 'подробности', 'расскажите', 'актуально', 'что за работа']
    
    if is_already_sent(event.sender_id):
        if any(word in text for word in positive_triggers):
            # Пауза "печатает..."
            await asyncio.sleep(random.randint(30, 60))
            await event.reply(DETAILED_OFFER)
            await client.send_message(REPORT_CHAT_ID, f"🔥 **ЕСТЬ КОНТАКТ!** Кандидат [id:{event.sender_id}](tg://user?id={event.sender_id}) запросил подробности.")

# --- [ЗАПУСК] ---
async def main():
    await client.start()
    print("🚀 Бот Hanna Oberg работает в режиме ручного расширения групп.")
    await client.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
