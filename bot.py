import asyncio
import os
import sqlite3
import random
import threading
import re
from datetime import datetime, timezone

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from openai import AsyncOpenAI
from http.server import BaseHTTPRequestHandler, HTTPServer

# ========================= КОНФИГУРАЦИЯ =========================
API_ID = 35975193
API_HASH = '5929ba2233799d47756cfee57b71c4a5'
REPORT_CHAT_ID = 8748575384

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SESSION_STR = os.getenv("TELEGRAM_SESSION")

ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
DB_PATH = "leads_v3.db"

TRIGGER_WORDS = [
    "пеший переход", "приехал сегодня", "очередь на границе", "еду в польшу", "выезжаю из",
    "карта побыту", "мельдунок", "pesel", "подача на карту", "виза закончилась",
    "ищу жилье", "сниму квартиру", "нужна комната", "ищу кавалерку",
    "ищу работу", "шукаю роботу", "подработка", "підробіток",
    "детский сад", "садик", "школа для ребенка", "800+", "dobry start",
    "тест", "test" # Добавил для твоей проверки
]

STOP_WORDS = ["ищем", "требуется", "вакансия", "набираем", "предлагаем", "услуги", "помогу"]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def extract_phone(text):
    phone_pattern = r'\+?\d{9,15}'
    match = re.search(phone_pattern, text)
    return match.group(0) if match else "Не указан"

# ====================== БАЗА ======================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('CREATE TABLE IF NOT EXISTS leads (user_id INTEGER PRIMARY KEY, status TEXT, category TEXT)')
    conn.close()

def get_status(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT status FROM leads WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        log(f"❌ Ошибка БД (get_status): {e}")
        return None

def set_status(user_id, status, category="unknown"):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR REPLACE INTO leads (user_id, status, category) VALUES (?, ?, ?)",
                     (user_id, status, category))
        conn.commit()
        conn.close()
    except Exception as e:
        log(f"❌ Ошибка БД (set_status): {e}")

# ====================== ИИ ======================
async def ai_check(text):
    log(f"🤖 Отправка текста в ИИ для анализа...")
    if not ai_client.api_key:
        log("⚠️ OPENAI_API_KEY не найден! Пропускаю проверку.")
        return True
    try:
        prompt = "Ответь ТОЛЬКО 'ДА' или 'НЕТ'. 'ДА' — если обычный человек ищет помощь, работу или жилье. 'НЕТ' — если это реклама, услуги или набор персонала."
        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": text}],
            max_tokens=5,
            temperature=0
        )
        answer = res.choices[0].message.content.strip().upper()
        log(f"🧠 ИИ вердикт: {answer}")
        return "ДА" in answer
    except Exception as e:
        log(f"❌ Ошибка ИИ: {e}")
        return False

# ====================== ОБРАБОТЧИК ======================
init_db()
client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    # 1. Логируем вообще любое входящее событие
    uid = event.sender_id
    if not uid: return

    sender = await event.get_sender()
    is_bot = getattr(sender, 'bot', False)
    
    # 2. Проверка на личку/группу
    if not event.is_group:
        return # Личные сообщения игнорируем (чтобы бот не зациклился сам на себе)

    chat = await event.get_chat()
    chat_title = getattr(chat, 'title', 'Unknown Group')
    
    log(f"📩 Новое сообщение в '{chat_title}' от {uid} ({sender.first_name})")

    # 3. Проверка на бота
    if is_bot:
        log(f"🤖 Пропуск: отправитель — бот.")
        return

    # 4. Проверка времени (увеличим до 30 минут на случай лагов сервера)
    msg_age = (datetime.now(timezone.utc) - event.date).total_seconds()
    if msg_age > 1800:
        log(f"⏳ Пропуск: сообщение слишком старое ({int(msg_age)} сек).")
        return

    text = event.raw_text
    text_lower = text.lower()

    # 5. Проверка стоп-слов
    for sw in STOP_WORDS:
        if sw in text_lower:
            log(f"⛔ Пропуск: найдено стоп-слово '{sw}'")
            return

    # 6. Проверка триггеров
    matched_trigger = next((word for word in TRIGGER_WORDS if word in text_lower), None)
    
    if not matched_trigger:
        log(f"⏭️ Пропуск: триггеры не найдены в тексте.")
        return

    # 7. Проверка, был ли этот лид уже обработан
    current_status = get_status(uid)
    if current_status is not None:
        log(f"🔁 Пропуск: пользователь {uid} уже есть в базе (статус: {current_status}).")
        return

    log(f"🎯 ПОПАДАНИЕ! Триггер: '{matched_trigger}'. Запускаю ИИ...")

    # 8. Проверка через ИИ
    if await ai_check(text):
        try:
            username = f"@{sender.username}" if sender.username else "Нет юзернейма"
            phone_in_text = extract_phone(text)
            user_phone = getattr(sender, 'phone', 'Скрыт')
            user_link = f"tg://user?id={uid}"

            report = (
                f"🎯 **НОВЫЙ ЛИД ПОДТВЕРЖДЕН**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"👤 Имя: {sender.first_name or '—'} {sender.last_name or ''}\n"
                f"🆔 ID: `{uid}`\n"
                f"🔗 Контакт: {username}\n"
                f"📱 Тел. в профиле: `{user_phone}`\n"
                f"📞 Тел. в тексте: `{phone_in_text}`\n"
                f"🏠 Группа: {chat_title}\n"
                f"🔗 Ссылка: [ОТКРЫТЬ ЧАТ]({user_link})\n\n"
                f"💬 Текст: _{text[:300]}_\n"
                f"🔍 Триггер: #{matched_trigger.replace(' ', '_')}"
            )

            log(f"📤 Отправка отчета в чат {REPORT_CHAT_ID}...")
            await client.send_message(REPORT_CHAT_ID, report, link_preview=False)
            
            # Ставим статус ТОЛЬКО после успешной отправки в чат
            set_status(uid, "sent")
            log(f"✅ Отчет успешно доставлен.")

            # Рандомная пауза перед ЛС
            wait_time = random.randint(40, 110)
            log(f"⏳ Ожидание {wait_time} сек перед ответом в ЛС...")
            await asyncio.sleep(wait_time)

            await client.send_message(uid, "Здравствуйте! Увидела ваш пост в группе. Актуально еще? Могу подсказать.")
            log(f"💌 Сообщение в ЛС отправлено.")

        except Exception as e:
            log(f"❌ КРИТИЧЕСКАЯ ОШИБКА ОБРАБОТКИ: {e}")
    else:
        log("🧠 ИИ решил, что это не лид (отказ).")

# ====================== ЗАПУСК ======================
async def main():
    def health():
        port = int(os.getenv("PORT", 8080))
        server = HTTPServer(('0.0.0.0', port),
            type('H', (BaseHTTPRequestHandler,), {'do_GET': lambda s: (s.send_response(200), s.end_headers(), s.wfile.write(b"OK"))}))
        server.serve_forever()
    
    threading.Thread(target=health, daemon=True).start()

    log("🔌 Подключение к Telegram...")
    await client.start()
    me = await client.get_me()
    log(f"🚀 Бот запущен на аккаунте: {me.first_name}")
    log(f"📝 Отчеты будут уходить в ID: {REPORT_CHAT_ID}")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
