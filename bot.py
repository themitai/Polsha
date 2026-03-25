import asyncio
import os
import sqlite3
import random
import threading
import sys
from datetime import datetime, timezone
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from openai import AsyncOpenAI
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- [КОНФИГУРАЦИЯ] ---
API_ID = 35523804
API_HASH = 'ff7673ebc0e925a32fb52693bdfae16f'
REPORT_CHAT_ID = 7238685565 
RECRUITER_TAG = "@hannaober"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SESSION_STR = os.getenv("TELEGRAM_SESSION")

ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
DB_PATH = '/app/data/bot_data.db' if os.path.exists('/app/data') else 'bot_data.db'

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# --- [СЕРВЕР ДЛЯ RAILWAY] ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"WORKING")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# --- [БАЗА ДАННЫХ] ---
def init_db():
    if os.path.dirname(DB_PATH): os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, status TEXT)')
    conn.close()

def get_status(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT status FROM users WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        return row[0] if row else None
    except: return None

def set_status(user_id, status):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR REPLACE INTO users (user_id, status) VALUES (?, ?)", (user_id, status))
        conn.commit()
        conn.close()
    except: pass

# --- [СТРОЖАЙШАЯ ПРОВЕРКА ИИ] ---
async def ai_check(text, mode="is_seeker"):
    log(f"🔎 ПРОВЕРКА ИИ ({mode}): '{text[:40]}...'")
    if not OPENAI_API_KEY:
        log("❌ ОШИБКА: Нет ключа OpenAI!")
        return True if mode == "is_interest" else False

    try:
        if mode == "is_seeker":
            sys_prompt = (
                "Ты — эксперт-фильтр для HR. Твоя единственная цель — найти сообщения от ЛЮДЕЙ, КОТОРЫЕ ИЩУТ РАБОТУ. "
                "СТРОГО ЗАПРЕЩЕНО (отвечай НЕТ): "
                "- Если это объявление о найме (например: 'Ищем сотрудников', 'Вакансия', 'Требуются'). "
                "- Если это реклама услуг (например: 'Делаю ремонт', 'Перевозки', 'Помогу с документами'). "
                "- Если это спам, новости или общие вопросы. "
                "СТРОГО РАЗРЕШЕНО (отвечай ДА): "
                "- Если человек прямо пишет: 'Ищу работу', 'Нужна подработка', 'Возьмусь за любую работу', 'Я мастер, ищу заказы'. "
                "Ответь только одним словом: ДА или НЕТ."
            )
        else:
            sys_prompt = "Человек ответил на наше предложение и хочет узнать подробности или согласен? Ответь ДА или НЕТ."

        res = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}],
            max_tokens=5, temperature=0 # 0 для максимальной точности
        )
        ans = res.choices[0].message.content.strip().upper()
        log(f"✅ ИИ ВЕРДИКТ: {ans}")
        return "ДА" in ans
    except Exception as e:
        log(f"❌ ОШИБКА ИИ: {e}")
        return True if mode == "is_interest" else False

# --- [ОСНОВНОЙ ОБРАБОТЧИК] ---
init_db()
client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    if not event.sender or event.sender.bot: return
    uid = event.sender_id
    username = f"@{event.sender.username}" if event.sender.username else f"ID: {uid}"
    first_name = event.sender.first_name or "User"

    # 1. ДИАЛОГ В ЛС
    if event.is_private:
        status = get_status(uid)
        if status in ["sent", "offered"]:
            if await ai_check(event.raw_text, "is_interest"):
                if status == "sent":
                    await event.reply("💼 **Условия работы:**\n• Удаленно (крипто-сфера)\n• ЗП: 2000€ + 2% бонус\n• Обучение 2 дня. График гибкий.\n\nВам подходит такое?")
                    set_status(uid, "offered")
                elif status == "offered":
                    await event.reply(f"Супер! Для начала работы и связи с командой напишите куратору: {RECRUITER_TAG}")
                    set_status(uid, "final")
                    await client.send_message(REPORT_CHAT_ID, f"🔥 **ЛИД ДОЖАТ:**\n👤 {first_name} ({username})\n✅ Получил контакт куратора.")

    # 2. МОНИТОРИНГ ГРУПП
    elif event.is_group:
        # Игнорируем сообщения старше 5 минут
        if (datetime.now(timezone.utc) - event.date).total_seconds() > 300: return
        
        if await ai_check(event.raw_text, "is_seeker"):
            if get_status(uid) is None:
                chat = await event.get_chat()
                group_name = chat.title
                msg_link = f"https://t.me/c/{str(event.chat_id)[4:]}/{event.id}" if not chat.username else f"https://t.me/{chat.username}/{event.id}"
                
                log(f"🎯 ЦЕЛЬ НАЙДЕНА: {username} в '{group_name}'")

                # ПОДРОБНЫЙ ОТЧЕТ В КАНАЛ
                report = (
                    f"🎯 **НАЙДЕН СОИСКАТЕЛЬ**\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"👤 **КТО:** {first_name} ({username})\n"
                    f"🏢 **ГДЕ:** {group_name}\n"
                    f"📝 **ТЕКСТ:** _{event.raw_text}_\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🔗 [ОТКРЫТЬ В ГРУППЕ]({msg_link})"
                )
                await client.send_message(REPORT_CHAT_ID, report, link_preview=False)
                
                # Пишем человеку
                set_status(uid, "sent")
                await asyncio.sleep(random.randint(25, 55))
                try: 
                    await client.send_message(uid, "Здравствуйте! Увидела ваш запрос в группе. У нас сейчас открыта удаленная вакансия (крипто-направление). Вам было бы интересно узнать детали?")
                    log(f"✅ Написали в ЛС {username}")
                except: 
                    log(f"❌ ЛС закрыты у {username}")
                    await client.send_message(REPORT_CHAT_ID, f"⚠️ Не смогла написать в ЛС @{event.sender.username or uid} (приватность).")

async def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    await client.start()
    log("🚀 СТРОГИЙ БОТ-HR ЗАПУЩЕН")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
