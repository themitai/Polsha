import asyncio
import random
import os
from datetime import datetime, timezone
from telethon import TelegramClient, events
from openai import AsyncOpenAI

# ================= КОНФИГУРАЦИЯ =================
API_ID = 35523804
API_HASH = 'ff7673ebc0e925a32fb52693bdfae16f'
SESSION_NAME = 'hr_assistant_session'
REPORT_CHAT_ID = 7238685565
RECRUITER_TAG = "@hannaober"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# База состояний пользователей
user_db = {}   # user_id -> "sent" / "offered" / "final"

# Минус-слова (отсекаем предложения услуг и вакансий)
STOP_PHRASES = [
    'ищем', 'вакансия', 'в офис', 'на склад', 'требуются', 'набираем',
    'услуги', 'фнс', 'снимаем', 'выполняю', 'пробив', 'помогу с',
    'оплата от', 'лс', 'запись', 'модели', 'тату', 'клиентов', 'ищу клиентов'
]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ================= ИИ-ПРОВЕРКИ =================
async def ai_check(text, task="is_seeker"):
    prompts = {
        "is_seeker": (
            "Ты должен определить, ищет ли человек работу. "
            "Ответь только ДА или НЕТ. "
            "ДА — если человек пишет: ищу работу, ищу подработку, нужна удалёнка, ищу вакансию, нужен ворк, ищу заработок. "
            "НЕТ — если человек предлагает услуги, работу, вакансию, помощь, пробив, ФНС и т.д."
        ),
        "is_interested": (
            "Определи, проявил ли человек интерес к предложенной вакансии. "
            "Ответь только ДА или НЕТ. "
            "ДА — если есть слова: да, интересно, подходит, хочу, расскажи, подробнее, ок, хорошо, давай, интересно, подойдёт."
        )
    }

    try:
        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompts[task]},
                {"role": "user", "content": text}
            ],
            max_tokens=5,
            temperature=0
        )
        answer = res.choices[0].message.content.strip().upper()
        return "ДА" in answer
    except Exception as e:
        log(f"AI error: {e}")
        return False

# ================= ОСНОВНОЙ ХЕНДЛЕР =================
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    if not event.sender or event.sender.bot:
        return

    user_id = event.sender_id
    text = event.raw_text.strip()

    # === 1. МОНИТОРИНГ ГРУПП ===
    if event.is_group:
        # Проверяем только свежие сообщения
        if (datetime.now(timezone.utc) - event.date).total_seconds() > 180:
            return

        text_lower = text.lower()
        if any(phrase in text_lower for phrase in STOP_PHRASES):
            return

        if await ai_check(text, "is_seeker"):
            if user_id not in user_db:
                chat = await event.get_chat()
                msg_link = f"https://t.me/c/{str(event.chat_id)[4:]}/{event.id}" if not chat.username else f"https://t.me/{chat.username}/{event.id}"

                report = (
                    f"🎯 **ЛИД НАЙДЕН**\n"
                    f"👤 **Имя:** {event.sender.first_name}\n"
                    f"🆔 **ID:** `{user_id}`\n"
                    f"💬 **Текст:** {text[:150]}\n"
                    f"📍 **Группа:** {chat.title}\n"
                    f"🔗 **Ссылка:** [ПЕРЕЙТИ]({msg_link})"
                )
                await client.send_message(REPORT_CHAT_ID, report, link_preview=False)

                # Отправляем первое сообщение
                user_db[user_id] = "sent"
                await asyncio.sleep(random.randint(18, 45))

                try:
                    await client.send_message(
                        user_id,
                        "Здравствуйте! Увидела ваш запрос в группе.\n\n"
                        "У нас сейчас открыта **удалённая позиция** в крипто-сфере (P2P-арбитраж).\n"
                        "Зарплата: **от 2000€ + 2% от профита**\n"
                        "Обучение: 2 дня онлайн\n"
                        "График: свободный\n\n"
                        "Вам интересно узнать подробнее?"
                    )
                    log(f"Первое сообщение отправлено кандидату {user_id}")
                except Exception:
                    log(f"ЛС закрыты у {user_id}")
                    user_db.pop(user_id, None)

    # === 2. ДИАЛОГ В ЛИЧКЕ ===
    elif event.is_private:
        status = user_db.get(user_id)

        if not status:
            return

        log(f"Ответ от кандидата {user_id}: {text}")

        if status == "sent":
            interested = await ai_check(text, "is_interested")
            if interested:
                await event.reply(
                    "Отлично! Кратко расскажу условия:\n\n"
                    "• Полностью удалённо\n"
                    "• Направление: крипто-арбитраж, P2P\n"
                    "• Зарплата: **от 2000€ фиксировано + 2% от профита**\n"
                    "• Обучение: 2 дня (онлайн)\n"
                    "• График: свободный\n\n"
                    "Подходит вам такое предложение?"
                )
                user_db[user_id] = "offered"
            else:
                await event.reply("Поняла. Если передумаете или появятся вопросы — пишите в любое время.")

        elif status == "offered":
            interested = await ai_check(text, "is_interested")
            if interested:
                await event.reply(
                    f"Супер! Теперь пишите напрямую нашему куратору Ханне — она даст полный доступ к обучению и всем материалам:\n\n"
                    f"{RECRUITER_TAG}\n\n"
                    "Будем рады видеть вас в команде! 💼"
                )
                user_db[user_id] = "final"

                # Отчёт в группу
                await client.send_message(
                    REPORT_CHAT_ID,
                    f"🔥 **ЛИД ДОЖАТ!**\n"
                    f"👤 @{event.sender.username or user_id}\n"
                    f"💬 {text[:120]}"
                )
            else:
                await event.reply("Поняла. Если появятся вопросы — обращайтесь в любое время.")

async def main():
    await client.start()
    log("🚀 БОТ ЗАПУЩЕН — поиск соискателей + полноценный диалог в ЛС")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
