import asyncio
import random
import os
import logging
from datetime import datetime, timezone

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from openai import AsyncOpenAI

# ========================= КОНФИГУРАЦИЯ =========================
API_ID = 35523804
API_HASH = 'ff7673ebc0e925a32fb52693bdfae16f'
SESSION_NAME = 'hr_assistant_session'

REPORT_CHAT_ID = 7238685565
RECRUITER_TAG = "@hannaober"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# База в памяти
user_db = {}

# Жёсткий фильтр стоп-фраз (предложения работы)
STOP_PHRASES = [
    'ищем', 'требуется', 'вакансия', 'вакансии', 'набираем', 'предлагаем работу',
    'открыта вакансия', 'компания ищет', 'мы ищем', 'зп от', 'оклад', 'в офис',
    'услуги', 'фнс', 'пробив', 'помогу', 'снимаем', 'выполняю', 'реклама',
]

def has_stop_phrase(text: str) -> bool:
    return any(phrase in text.lower() for phrase in STOP_PHRASES)

# ========================= ЛОГИРОВАНИЕ =========================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger(__name__)

# ========================= ИИ =========================
async def ai_check(text: str, task: str = "is_seeker") -> bool:
    prompts = {
        "is_seeker": (
            "Отвечай ТОЛЬКО словом ДА или НЕТ.\n"
            "ДА — если человек явно ищет работу (ищу, подработку, удалёнку, рассмотрю предложения и т.п.)\n"
            "НЕТ — если предлагает работу, услуги, вакансии, рекламу."
        ),
        "is_interested": (
            "Человек ответил на предложение работы и проявил интерес?\n"
            "Ответы вроде: да, давай, интересно, расскажи, хочу, подойдёт, ок, хорошо — это ДА.\n"
            "Отвечай ТОЛЬКО ДА или НЕТ."
        )
    }

    try:
        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompts[task]},
                      {"role": "user", "content": text}],
            max_tokens=10,
            temperature=0
        )
        answer = res.choices[0].message.content.upper().strip()
        return "ДА" in answer
    except Exception as e:
        log.error(f"OpenAI ошибка: {e}")
        return False


# ========================= ОБРАБОТЧИК =========================
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)


@client.on(events.NewMessage)
async def handler(event):
    if not event.sender or getattr(event.sender, 'bot', False):
        return

    user_id = event.sender_id
    text = event.raw_text.strip()

    # ====================== ЛИЧНЫЕ СООБЩЕНИЯ ======================
    if event.is_private or event.chat_id == user_id or event.to_id.user_id == user_id:
        status = user_db.get(user_id)

        log.info(f"[ЛИЧКА] Сообщение от {user_id} | статус: {status} | текст: {text[:100]}")

        if not status:
            log.info(f"[ЛИЧКА] Игнорируем — нет статуса для {user_id}")
            return

        try:
            if await ai_check(text, "is_interested"):
                log.info(f"[ЛИЧКА] ИИ подтвердил интерес от {user_id} (статус: {status})")

                if status == "sent":
                    await event.reply(
                        "Условия: удаленно, крипто-направление. "
                        "ЗП: 2000€ + 2%. Обучение 2 дня. Подходит?"
                    )
                    user_db[user_id] = "offered"
                    log.info(f"[ЛИЧКА] Отправили условия кандидату {user_id}")

                elif status == "offered":
                    await event.reply(
                        f"Супер! Пишите куратору Ханне, она даст доступ к обучению: {RECRUITER_TAG}"
                    )
                    user_db[user_id] = "final"
                    await client.send_message(
                        REPORT_CHAT_ID,
                        f"🔥 **ЛИД ДОЖАТ:** @{event.sender.username or user_id}"
                    )
                    log.info(f"[ЛИЧКА] Лид дожат! {user_id}")
            else:
                log.info(f"[ЛИЧКА] ИИ сказал НЕТ интересу от {user_id}")
        except Exception as e:
            log.error(f"Ошибка в личке {user_id}: {e}")
        return   # ← важно не продолжать обработку как группу

    # ====================== ГРУППЫ ======================
    if not event.is_group:
        return

    if (datetime.now(timezone.utc) - event.date).total_seconds() > 120:
        return

    if has_stop_phrase(text):
        return

    if await ai_check(text, "is_seeker"):
        if user_id not in user_db:
            try:
                chat = await event.get_chat()
                msg_link = (f"https://t.me/{chat.username}/{event.id}" if chat.username
                            else f"https://t.me/c/{str(event.chat_id)[4:]}/{event.id}")

                report = (
                    f"🎯 **ЛИД НАЙДЕН**\n"
                    f"👤 **Имя:** {event.sender.first_name or 'Без имени'}\n"
                    f"🆔 **ID:** `{user_id}`\n"
                    f"💬 **Текст:** {text[:150]}{'...' if len(text) > 150 else ''}\n"
                    f"📍 **Группа:** {chat.title}\n"
                    f"🔗 **Ссылка:** [ПЕРЕЙТИ]({msg_link})"
                )

                await client.send_message(REPORT_CHAT_ID, report, link_preview=False)

                user_db[user_id] = "sent"
                await asyncio.sleep(random.randint(18, 38))

                await client.send_message(
                    user_id,
                    "Здравствуйте! Увидела ваш запрос в группе. "
                    "У нас сейчас открыта удаленная позиция (крипто-сфера, без опыта). "
                    "Вам интересно узнать детали?"
                )

                log.info(f"✅ Первое сообщение отправлено кандидату {user_id}")

            except FloodWaitError as e:
                log.warning(f"FloodWait {e.seconds} сек")
                await asyncio.sleep(e.seconds + 5)
            except Exception as e:
                log.error(f"Ошибка при отправке лиду {user_id}: {e}")


# ========================= ЗАПУСК =========================
async def main():
    await client.start()
    log.info("🚀 БОТ ЗАПУЩЕН — исправлена обработка ответов в личке")
    await client.run_until_disconnected()


if __name__ == '__main__':
    asyncio.run(main())
