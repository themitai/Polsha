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

user_db = {}
dialog_owner = {}

# ========================= ЖЁСТКИЙ ФИЛЬТР =========================
STOP_PHRASES = [
    "ищем", "требуется", "требуются", "вакансия", "вакансии", "набираем", "набираємо",
    "оператор чату", "стример", "модель", "чат", "стримы", "заробітна плата", "зарплата від",
    "від", "zł", "зл", "кар’єрного зростання", "карьерного роста", "работодатель",
    "предлагаем", "предлагаємо", "компанія", "компания", "в команду", "в офіс", "на склад",
    "оплата від", "графік", "график", "удалённо от компании"
]

def has_stop_phrase(text: str) -> bool:
    text_lower = text.lower()
    return any(phrase in text_lower for phrase in STOP_PHRASES)

# ========================= ЛОГИРОВАНИЕ =========================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger(__name__)

# ========================= ИИ (усиленный) =========================
async def ai_check(text: str, task: str = "is_seeker") -> bool:
    prompts = {
        "is_seeker": (
            "Ты — очень строгий фильтр. Отвечай ТОЛЬКО одним словом: ДА или НЕТ.\n\n"
            "ДА — только если человек **сам ищет работу**: "
            "пишет 'ищу работу', 'ищу подработку', 'нужна работа', 'ищу удалёнку', "
            "'рассмотрю предложения', 'есть ли вакансии для меня' и т.п.\n\n"
            "НЕТ — во всех остальных случаях, особенно если:\n"
            "- предлагает вакансию\n"
            "- пишет про зарплату, график, условия для сотрудников\n"
            "- упоминает 'оператор чату', 'стример', 'модель', 'чат'\n"
            "- пишет на украинском/польском о найме людей\n"
            "Будь максимально жёстким. Даже малейшее подозрение — НЕТ."
        ),
        "is_interested": (
            "Человек проявил интерес к предложению работы? "
            "Да, давай, интересно, расскажи, хочу, ок, хорошо, подойдёт — это ДА. "
            "Отвечай ТОЛЬКО ДА или НЕТ."
        )
    }

    try:
        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompts[task]},
                      {"role": "user", "content": text}],
            max_tokens=10,
            temperature=0.0
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

    # ====================== ЛИЧНЫЕ СООБЩЕНИЯ ======================
    is_private = (
        getattr(event, 'is_private', False) or
        event.chat_id == user_id or
        (getattr(event, 'to_id', None) and hasattr(event.to_id, 'user_id') and event.to_id.user_id == user_id)
    )

    if is_private:
        status = user_db.get(user_id)
        log.info(f"[ЛИЧКА] От {user_id} | статус={status} | текст=\"{text}\"")

        if status:
            try:
                if await ai_check(text, "is_interested"):
                    if status == "sent":
                        await event.reply("Условия: удаленно, крипто-направление. ЗП: 2000€ + 2%. Обучение 2 дня. Подходит?")
                        user_db[user_id] = "offered"
                        log.info(f"[ЛИЧКА] Отправили условия → {user_id}")

                    elif status == "offered":
                        await event.reply(f"Супер! Пиши куратору Ханне: {RECRUITER_TAG}")
                        user_db[user_id] = "final"
                        await client.send_message(REPORT_CHAT_ID, f"🔥 **ЛИД ДОЖАТ:** @{event.sender.username or user_id}")
                        log.info(f"[ЛИЧКА] ЛИД ДОЖАТ → {user_id}")
            except Exception as e:
                log.error(f"Ошибка в личке {user_id}: {e}")
        return

    # ====================== ГРУППЫ — ЖЁСТКАЯ ФИЛЬТРАЦИЯ ======================
    if not event.is_group:
        return

    if (datetime.now(timezone.utc) - event.date).total_seconds() > 120:
        return

    # Первая жёсткая отсечка по ключевым словам
    if has_stop_phrase(text):
        log.info(f"[ФИЛЬТР] Стоп-фраза → пропущено: {text[:80]}...")
        return

    # Вторая проверка через ИИ (самая строгая)
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
                dialog_owner[user_id] = True

                await asyncio.sleep(random.randint(18, 40))

                await client.send_message(
                    user_id,
                    "Здравствуйте! Увидела ваш запрос в группе. "
                    "У нас открыта удаленная позиция (крипто-сфера, без опыта). "
                    "Вам интересно узнать детали?"
                )
                log.info(f"✅ Бот написал первому сообщению → {user_id} (Кира Соколова и подобные теперь должны отсеиваться)")

            except FloodWaitError as e:
                log.warning(f"FloodWait {e.seconds} сек")
                await asyncio.sleep(e.seconds + 5)
            except Exception as e:
                log.error(f"Ошибка отправки {user_id}: {e}")


async def main():
    await client.start()
    log.info("🚀 БОТ ЗАПУЩЕН — ЖЁСТКАЯ ФИЛЬТРАЦИЯ (только соискатели)")
    await client.run_until_disconnected()


if __name__ == '__main__':
    asyncio.run(main())
