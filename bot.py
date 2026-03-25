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

# ========================= ЖЁСТКИЙ СПИСОК СТОП-ФРАЗ =========================
# Теперь бот почти не будет ловить тех, кто предлагает работу
STOP_PHRASES = [
    'ищем', 'ищем сотрудника', 'ищем человека', 'ищем на удаленку', 'ищем в команду',
    'требуется', 'требуются', 'требуется сотрудник', 'требуется человек',
    'вакансия', 'вакансии', 'открыта вакансия', 'открыты вакансии',
    'набираем', 'набираем в команду', 'набираем сотрудников',
    'предлагаем работу', 'предлагаем вакансию', 'работодатель',
    'компания ищет', 'компания набирает', 'мы ищем',
    'зп от', 'зарплата от', 'оклад', 'график работы', 'полный день',
    'в офис', 'на склад', 'курьер', 'водитель', 'менеджер по продажам',
    'удаленная работа от компании', 'работа в компании', 'присоединяйся к нам',
    'услуги', 'фнс', 'пробив', 'помогу с', 'оформлю', 'снимаем', 'выполняю',
    'оплата от', 'лс', 'запись', 'модели', 'тату', 'клиентов', 'реклама',
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

# ========================= ИИ (усиленный промпт) =========================
async def ai_check(text: str, task: str = "is_seeker") -> bool:
    prompts = {
        "is_seeker": (
            "ТЫ — СТРОГИЙ ФИЛЬТР СОИСКАТЕЛЕЙ. "
            "Отвечай ТОЛЬКО одним словом: ДА или НЕТ.\n\n"
            "ДА — если человек явно ИЩЕТ РАБОТУ: "
            "'ищу работу', 'ищу подработку', 'нужен ворк', 'ищу удалёнку', "
            "'есть ли вакансии для меня', 'готов работать', 'рассмотрю предложения' и т.п.\n\n"
            "НЕТ — во всех остальных случаях:\n"
            "• если человек предлагает работу, вакансию, набирает людей\n"
            "• если пишет 'ищем', 'требуется', 'вакансия', 'набираем'\n"
            "• если предлагает услуги, ФНС, пробив, помощь\n"
            "• если это реклама, продажа, тату, модели и т.д.\n"
            "Будь максимально строгим. Даже небольшое подозрение на предложение работы — НЕТ."
        ),
        "is_interested": "Человек проявил интерес к вакансии? Ответь только ДА или НЕТ."
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
        answer = res.choices[0].message.content.upper().strip()
        return "ДА" in answer
    except Exception as e:
        log.error(f"Ошибка OpenAI: {e}")
        return False


# ========================= ТЕЛЕГРАМ КЛИЕНТ =========================
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)


@client.on(events.NewMessage)
async def handler(event):
    if not event.sender or event.sender.bot:
        return

    user_id = event.sender_id
    text = event.raw_text.strip()

    # ====================== 1. ЛИЧНЫЕ СООБЩЕНИЯ ======================
    if event.is_private or event.chat_id == user_id:
        status = user_db.get(user_id)
        if not status:
            return

        log.info(f"Ответ от кандидата {user_id}: {text}")

        try:
            if await ai_check(text, "is_interested"):
                if status == "sent":
                    await event.reply(
                        "Условия: удаленно, крипто-направление. "
                        "ЗП: 2000€ + 2%. Обучение 2 дня. Подходит?"
                    )
                    user_db[user_id] = "offered"

                elif status == "offered":
                    await event.reply(
                        f"Супер! Пишите куратору Ханне, она даст доступ к обучению: {RECRUITER_TAG}"
                    )
                    user_db[user_id] = "final"

                    await client.send_message(
                        REPORT_CHAT_ID,
                        f"🔥 **ЛИД ДОЖАТ:** @{event.sender.username or user_id}"
                    )
        except Exception as e:
            log.error(f"Ошибка при ответе кандидату {user_id}: {e}")
        return

    # ====================== 2. МОНИТОРИНГ ГРУПП (ЖЁСТКАЯ ФИЛЬТРАЦИЯ) ======================
    if not event.is_group:
        return

    # Только свежие сообщения
    if (datetime.now(timezone.utc) - event.date).total_seconds() > 120:
        return

    # === ЖЁСТКАЯ ПРОВЕРКА 1: стоп-фразы ===
    if has_stop_phrase(text):
        return

    # === ЖЁСТКАЯ ПРОВЕРКА 2: ИИ ===
    if await ai_check(text, "is_seeker"):
        if user_id not in user_db:
            try:
                chat = await event.get_chat()

                if chat.username:
                    msg_link = f"https://t.me/{chat.username}/{event.id}"
                else:
                    msg_link = f"https://t.me/c/{str(event.chat_id)[4:]}/{event.id}"

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
                await asyncio.sleep(random.randint(15, 35))

                await client.send_message(
                    user_id,
                    "Здравствуйте! Увидела ваш запрос в группе. "
                    "У нас сейчас открыта удаленная позиция (крипто-сфера, без опыта). "
                    "Вам интересно узнать детали?"
                )

                log.info(f"✅ Отправлено первое сообщение кандидату {user_id}")

            except FloodWaitError as e:
                log.warning(f"FloodWaitError: ждём {e.seconds} сек")
                await asyncio.sleep(e.seconds + 5)
            except Exception as e:
                log.error(f"Ошибка при обработке лида {user_id}: {e}")


# ========================= ЗАПУСК =========================
async def main():
    await client.start()
    log.info("🚀 БОТ ЗАПУЩЕН С ЖЁСТКОЙ ФИЛЬТРАЦИЕЙ (только соискатели)")
    await client.run_until_disconnected()


if __name__ == '__main__':
    asyncio.run(main())
