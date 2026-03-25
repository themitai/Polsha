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

user_db = {}   # user_id → "sent" / "offered"

STOP_PHRASES = [
    "ищем", "требуется", "вакансия", "набираем", "есть место", "прекрасное место",
    "оператор чата", "стример", "оплата от", "зарплата от", "от 2000", "оплачиваемый отпуск",
    "хорошая команда", "карьерного", "заробітна плата", "від", "zł", "предлагаем"
]

def has_stop_phrase(text: str) -> bool:
    if any(p in text.lower() for p in STOP_PHRASES):
        log.info(f"[СТОП-ФРАЗА] Отсечено: {text[:80]}...")
        return True
    return False

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger(__name__)

async def ai_check(text: str, task: str = "is_seeker") -> bool:
    prompts = {
        "is_seeker": "Отвечай ТОЛЬКО ДА или НЕТ. ДА — только если человек САМ ищет работу.",
        "is_interested": "Человек проявил интерес? да, давай, интересно, расскажи, хочу, ок, подробнее — это ДА. Отвечай ТОЛЬКО ДА или НЕТ."
    }
    try:
        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompts[task]}, {"role": "user", "content": text}],
            max_tokens=8,
            temperature=0
        )
        return "ДА" in res.choices[0].message.content.upper()
    except Exception as e:
        log.error(f"OpenAI ошибка: {e}")
        return False


client = TelegramClient(SESSION_NAME, API_ID, API_HASH)


@client.on(events.NewMessage)
async def handler(event):
    if not event.sender or getattr(event.sender, 'bot', False):
        return

    user_id = event.sender_id
    text = event.raw_text.strip()

    # ====================== ЛИЧКА — МАКСИМАЛЬНО НАДЁЖНАЯ ПРОВЕРКА ======================
    is_personal = (
        event.is_private or
        event.chat_id == user_id or
        (event.to_id and hasattr(event.to_id, 'user_id') and event.to_id.user_id == user_id)
    )

    if is_personal:
        status = user_db.get(user_id)
        log.info(f"[ЛИЧКА] === СООБЩЕНИЕ ОТ {user_id} === статус={status} | текст: '{text}'")

        if status:
            interested = await ai_check(text, "is_interested")
            log.info(f"[ЛИЧКА] ИИ is_interested = {interested}")

            if interested:
                if status == "sent":
                    await event.reply(
                        "Условия: удаленно, крипто-направление. ЗП: 2000€ + 2%. Обучение 2 дня. Подходит?"
                    )
                    user_db[user_id] = "offered"
                    log.info(f"[ЛИЧКА] → Отправили условия кандидату {user_id}")

                elif status == "offered":
                    await event.reply(f"Супер! Пишите куратору Ханне: {RECRUITER_TAG}")
                    user_db[user_id] = "final"
                    await client.send_message(
                        REPORT_CHAT_ID,
                        f"🔥 **ЛИД ДОЖАТ:** @{event.sender.username or user_id}"
                    )
                    log.info(f"[ЛИЧКА] → ЛИД ДОЖАТ {user_id}")
        else:
            log.info(f"[ЛИЧКА] Нет статуса для {user_id} — игнорируем")
        return   # ← обязательно выходим

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
                msg_link = f"https://t.me/{chat.username}/{event.id}" if getattr(chat, 'username', None) \
                    else f"https://t.me/c/{str(event.chat_id)[4:]}/{event.id}"

                report = (
                    f"🎯 **ЛИД НАЙДЕН**\n"
                    f"👤 **Имя:** {event.sender.first_name or '—'}\n"
                    f"🆔 **ID:** `{user_id}`\n"
                    f"💬 **Текст:** {text[:140]}\n"
                    f"📍 **Группа:** {chat.title}\n"
                    f"🔗 [Ссылка]({msg_link})"
                )
                await client.send_message(REPORT_CHAT_ID, report, link_preview=False)

                user_db[user_id] = "sent"

                await asyncio.sleep(random.randint(15, 35))

                await client.send_message(
                    user_id,
                    "Здравствуйте! Увидела ваш запрос в группе. "
                    "У нас открыта удаленная позиция (крипто-сфера, без опыта). "
                    "Вам интересно узнать детали?"
                )
                log.info(f"✅ Отправили первое сообщение → {user_id}")

            except Exception as e:
                log.error(f"Ошибка отправки лиду {user_id}: {e}")


async def main():
    await client.start()
    log.info("🚀 БОТ ЗАПУЩЕН — максимально надёжная обработка ЛС")
    await client.run_until_disconnected()


if __name__ == '__main__':
    asyncio.run(main())
