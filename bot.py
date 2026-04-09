import asyncio
import os
import sqlite3
import random
import threading
import re  # Добавили для поиска номеров
from datetime import datetime, timezone

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
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
    "детский сад", "садик", "школа для ребенка", "800+", "dobry start"
]

STOP_WORDS = ["ищем", "требуется", "вакансия", "набираем", "предлагаем", "услуги", "помогу"]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# Функция поиска номера телефона в тексте
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
    except:
        return None

def set_status(user_id, status, category="unknown"):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR REPLACE INTO leads (user_id, status, category) VALUES (?, ?, ?)",
                     (user_id, status, category))
        conn.commit()
        conn.close()
    except Exception as e:
        log(f"❌ Ошибка БД: {e}")

# ====================== ИИ ======================
async def ai_check(text):
    if not ai_client: return True
    try:
        prompt = "Ответь ТОЛЬКО 'ДА' или 'НЕТ'. 'ДА' — если обычный человек ищет помощь, работу или жилье. 'НЕТ' — если это реклама или услуги."
        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": text}],
            max_tokens=5,
            temperature=0
        )
        return "ДА" in res.choices[0].message.content.strip().upper()
    except:
        return False

# ====================== ОБРАБОТЧИК ======================
init_db()
client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    if not event.sender_id or not event.is_group: return
    
    # Проверка на ботов
    sender = await event.get_sender()
    if getattr(sender, 'bot', False): return

    uid = event.sender_id
    text = event.raw_text
    text_lower = text.lower()

    # Пропускаем старые сообщения
    if (datetime.now(timezone.utc) - event.date).total_seconds() > 600: return

    # Проверка стоп-слов
    if any(word in text_lower for word in STOP_WORDS): return

    # Проверка триггеров
    matched_trigger = next((word for word in TRIGGER_WORDS if word in text_lower), None)
    
    if matched_trigger and get_status(uid) is None:
        log(f"🔍 Триггер '{matched_trigger}' у {uid}. Проверка ИИ...")
        
        if await ai_check(text):
            try:
                chat = await event.get_chat()
                username = f"@{sender.username}" if sender.username else "Нет юзернейма"
                phone_in_text = extract_phone(text)
                user_phone = getattr(sender, 'phone', 'Скрыт')
                user_link = f"tg://user?id={uid}"

                report = (
                    f"🎯 **НОВЫЙ ЛИД НАЙДЕН**\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"👤 Имя: {sender.first_name or '—'} {sender.last_name or ''}\n"
                    f"🆔 ID: `{uid}`\n"
                    f"🔗 Контакт: {username}\n"
                    f"📱 Тел. в профиле: `{user_phone}`\n"
                    f"📞 Тел. в тексте: `{phone_in_text}`\n"
                    f"🏠 Группа: {chat.title}\n"
                    f"🔗 Ссылка на личку: [ОТКРЫТЬ ЧАТ]({user_link})\n\n"
                    f"💬 Текст: _{text[:300]}_\n"
                    f"🔍 Триггер: #{matched_trigger.replace(' ', '_')}"
                )

                # 1. Сначала отправляем отчет в чат
                await client.send_message(REPORT_CHAT_ID, report, link_preview=False)
                log(f"✅ Отчет по {uid} отправлен.")

                # 2. Только после успеха помечаем в базе
                set_status(uid, "sent")

                # 3. Пауза перед личным сообщением (имитация человека)
                wait_time = random.randint(30, 90)
                log(f"⏳ Ждем {wait_time} сек перед ответом в ЛС...")
                await asyncio.sleep(wait_time)

                await client.send_message(uid, "Здравствуйте! Увидела ваш пост в группе. Актуально еще? Могу подсказать по вашему вопросу.")
                log(f"💌 Сообщение в ЛС пользователю {uid} отправлено.")

            except Exception as e:
                log(f"❌ Ошибка обработки лида {uid}: {e}")

# ====================== ЗАПУСК ======================
async def main():
    # Health check для Railway/Heroku
    def health():
        port = int(os.getenv("PORT", 8080))
        server = HTTPServer(('0.0.0.0', port),
            type('H', (BaseHTTPRequestHandler,), {'do_GET': lambda s: (s.send_response(200), s.end_headers(), s.wfile.write(b"OK"))}))
        server.serve_forever()
    
    threading.Thread(target=health, daemon=True).start()

    await client.start()
    me = await client.get_me()
    log(f"🚀 Аккаунт {me.first_name} в сети. Слушаю группы...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
