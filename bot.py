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

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# --- [ЛОГИКА ИИ] ---
async def ai_decision(text, system_prompt):
    try:
        response = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": text}],
            max_tokens=10, temperature=0
        )
        return "ДА" in response.choices[0].message.content.strip().upper()
    except: return False

# --- [ГЛАВНЫЙ ОБРАБОТЧИК] ---

@client.on(events.NewMessage)
async def handler(event):
    if event.is_group:
        chat_id = str(event.chat_id)
        
        # Читаем список известных чатов
        if os.path.exists(KNOWN_CHATS_FILE):
            with open(KNOWN_CHATS_FILE, "r") as f:
                known = f.read().splitlines()
        else:
            known = []

        # Если чат новый — запоминаем и сообщаем
        if chat_id not in known:
            with open(KNOWN_CHATS_FILE, "a") as f:
                f.write(f"{chat_id}\n")
            chat = await event.get_chat()
            # Отправляем уведомление ТОЛЬКО если это реально новый чат после старта
            await client.send_message(REPORT_CHAT_ID, f"✅ **НОВЫЙ ЧАТ В РАБОТЕ:** {chat.title}")
            return

        # Логика поиска лидов
        if (datetime.now(timezone.utc) - event.date).total_seconds() > 60: return
        if not event.sender or event.sender.bot: return

        prompt = "Ты HR. Если человек ищет работу/заработок, ответь только 'ДА'. Иначе 'НЕТ'."
        if await ai_decision(event.raw_text, prompt):
            # Проверка базы отправленных
            if not os.path.exists(DB_FILE): open(DB_FILE, "w").close()
            with open(DB_FILE, "r") as f: sent = f.read().splitlines()
            
            if str(event.sender_id) not in sent:
                user_link = f"tg://user?id={event.sender_id}"
                await client.send_message(REPORT_CHAT_ID, f"🤖 **ИИ НАШЕЛ ЛИДА**\n👤: {event.sender.first_name}\n📝: {event.raw_text[:100]}\n👉 [ОТКРЫТЬ]({user_link})")
                
                await asyncio.sleep(random.randint(300, 600))
                try:
                    await client.send_message(event.sender_id, "Здравствуйте! Увидела ваше сообщение в группе. У нас есть вакансия на удаленку (крипто-сфера, без опыта). Вам было бы интересно узнать детали?")
                    with open(DB_FILE, "a") as f: f.write(f"{event.sender_id}\n")
                except:
                    await client.send_message(REPORT_CHAT_ID, f"❌ Закрыты ЛС у `{event.sender_id}`")

    elif event.is_private:
        # Логика ответов в ЛС (как раньше)
        if not event.sender or event.sender.bot: return
        if not os.path.exists(DB_FILE): return
        with open(DB_FILE, "r") as f: sent = f.read().splitlines()
        
        if str(event.sender_id) in sent:
            prompt = "Если человек проявил интерес к работе, ответь только 'ДА'."
            if await ai_decision(event.raw_text, prompt):
                await asyncio.sleep(random.randint(40, 80))
                await event.reply(f"Суть: обработка заявок (удаленно). Подробнее тут: {RECRUITER_TAG}")
                await client.send_message(REPORT_CHAT_ID, f"🔥 **ЛИД ГОТОВ!** ID: `{event.sender_id}`")

async def main():
    await client.start()
    
    # ПРЕДЗАГРУЗКА: Запоминаем все текущие чаты при старте, чтобы не спамить
    print("Инициализация чатов...")
    current_chats = []
    async for dialog in client.iter_dialogs():
        if dialog.is_group:
            current_chats.append(str(dialog.id))
    
    with open(KNOWN_CHATS_FILE, "w") as f:
        f.write("\n".join(current_chats) + "\n")
        
    print("🚀 Бот запущен. Текущие чаты проигнорированы, слежу за новыми.")
    await client.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
