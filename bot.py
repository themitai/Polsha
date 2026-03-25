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

# ========================= МАКСИМАЛЬНО ЖЁСТКИЙ ФИЛЬТР =========================
STOP_PHRASES = [
    "ищем", "требуется", "требуются", "вакансия", "вакансии", "набираем", "набираємо",
    "есть место", "прекрасное место", "оператор чата", "оператора чата", "стример",
    "оплата от", "зарплата от", "от 2000", "от 2000$", "оплачиваемый отпуск",
    "хорошая команда", "команда", "карьерного роста", "заробітна плата", "від",
    "zł", "зл", "удалёнка от компании", "работа в компании", "предлагаем", "предлагаємо",
    "в команду", "в офис", "на склад", "модель", "чат", "стримы"
]

def has_stop_phrase(text: str) -> bool:
    text_lower = text.lower()
    if any(phrase in text_lower for phrase in STOP_PHRASES):
        log.info(f"[СТОП-ФРАЗА] Отсечено: {text[:100]}...")
        return True
    return False

# ========================= ЛОГИРОВАНИЕ =========================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger(__name__)

# ========================= ИИ — ОЧЕНЬ СТРОГИЙ =========================
async def ai_check(text: str, task: str = "is_seeker") -> bool:
    prompts = {
        "is_seeker": (
            "ТЫ — ЖЁСТКИЙ ФИЛЬТР. Отвечай ТОЛЬКО одним словом: ДА или НЕТ.\n\n"
            "ДА — исключительно если человек САМ ИЩЕТ РАБОТУ:\n"
            "ищу работу, ищу подработку, нужна работа, ищу удалёнку, рассмотрю предложения и т.п.\n\n"
            "НЕТ — во всех остальных случаях! Особенно если:\n"
            "- предлагает вакансию ('есть место', 'оператор чата', 'оплата от', 'от 2000$', 'оплачиваемый отпуск', 'хорошая команда')\n"
            "- пишет про зарплату, условия, команду, отпуск\n"
            "- любое предложение работы — НЕТ.\n"
            "Будь максимально строгим. Даже небольшое подозрение — отвечай НЕТ."
        ),
        "is_interested": (
            "Человек проявил интерес к твоему предложению работы? "
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
        answer = res.choices[0].message.content.upper().strip()
        return "ДА" in answer
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

    # ====================== ГРУППЫ — СУПЕР ЖЁСТКАЯ ФИЛЬТРАЦИЯ ======================
    if not event.is_group:
        return

    if (datetime.now(timezone.utc) - event.date).total_seconds() > 120:
        return

    # 1. Стоп-фразы
    if has_stop_phrase(text):
        return

    # 2. ИИ (финальная проверка)
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
                log.info(f"✅ Бот написал соискателю → {user_id}")

            except FloodWaitError as e:
                log.warning(f"FloodWait {e.seconds} сек")
                await asyncio.sleep(e.seconds + 5)
            except Exception as e:
                log.error(f"Ошибка отправки {user_id}: {e}")


async def main():
    await client.start()
    log.info("🚀 БОТ ЗАПУЩЕН — МАКСИМАЛЬНО ЖЁСТКАЯ ФИЛЬТРАЦИЯ (только те, кто ищет работу)")
    await client.run_until_disconnected()


if __name__ == '__main__':
    asyncio.run(main())
