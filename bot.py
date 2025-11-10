import asyncio
import os
import aiosqlite
import yt_dlp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.types import FSInputFile
from dotenv import load_dotenv
from datetime import datetime

# === Загружаем настройки из .env ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMINS = [int(x) for x in os.getenv("ADMINS", "0").split(",") if x.strip() and x != "0"]
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
VK_SOURCE = os.getenv("VK_SOURCE", "").strip()

# === Инициализация бота ===
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# === Инициализация базы данных ===
async def init_db():
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vk_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vk_id TEXT UNIQUE,
                title TEXT,
                url TEXT,
                posted INTEGER DEFAULT 0
            )
        """)
        await db.commit()

# === Получение всех видео из VK плейлиста ===
async def fetch_vk_videos():
    print(f"🔍 Проверяю все видео из VK: {VK_SOURCE}")
    try:
        ydl_opts = {
            "quiet": True,
            "extract_flat": True,
            "skip_download": True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(VK_SOURCE, download=False)
            entries = info.get("entries", [])

        async with aiosqlite.connect("bot.db") as db:
            for video in entries:
                vk_id = video.get("id")
                title = video.get("title", "Видео из VK")
                url = video.get("url")

                # Добавляем, если нет в базе
                cur = await db.execute("SELECT vk_id FROM vk_videos WHERE vk_id=?", (vk_id,))
                exists = await cur.fetchone()
                if not exists:
                    await db.execute(
                        "INSERT INTO vk_videos (vk_id, title, url) VALUES (?, ?, ?)",
                        (vk_id, title, url)
                    )
                    print(f"➕ Добавлено в очередь: {title}")
            await db.commit()
        print("✅ Все видео добавлены в базу (если не было).")
    except Exception as e:
        print(f"❌ Ошибка при получении списка видео: {e}")

# === Публикация следующего видео ===
async def post_next_video():
    async with aiosqlite.connect("bot.db") as db:
        cur = await db.execute("SELECT vk_id, title, url FROM vk_videos WHERE posted=0 ORDER BY id ASC LIMIT 1")
        row = await cur.fetchone()

        if not row:
            print("📭 Нет новых видео для публикации.")
            return

        vk_id, title, url = row
        print(f"🎬 Публикую: {title}")

        try:
            os.makedirs("videos", exist_ok=True)
            file_path = f"videos/{vk_id}.mp4"

            # Скачиваем видео
            ydl_opts = {"outtmpl": file_path, "quiet": True, "format": "best"}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            caption = f"{title}\n\n<a href='https://t.me/billysbest'>@Billy's Family</a>"

            # Публикуем в канал
            await bot.send_video(
                chat_id=CHANNEL_ID,
                video=FSInputFile(file_path),
                caption=caption
            )

            # Помечаем как опубликованное
            await db.execute("UPDATE vk_videos SET posted=1 WHERE vk_id=?", (vk_id,))
            await db.commit()

            print(f"✅ Опубликовано: {title}")

            # Отправляем уведомление админу
            for admin_id in ADMINS:
                await bot.send_message(admin_id, f"✅ Опубликовано новое видео: {title}")

        except Exception as e:
            print(f"⚠️ Ошибка при публикации видео: {e}")

# === Планировщик (каждые 1.5 часа) ===
async def scheduler():
    await fetch_vk_videos()  # один раз при запуске загрузим весь список
    while True:
        await post_next_video()
        print("⏰ Следующая публикация через 1.5 часа...")
        await asyncio.sleep(90 * 60)  # 90 минут

# === Команда /start ===
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    if message.from_user.id in ADMINS:
        await message.answer("👋 Привет! Бот работает.\nОн публикует видео из VK каждые 1.5 часа.")
    else:
        await message.answer("⛔ У вас нет прав администратора.")

# === Запуск ===
async def main():
    await init_db()
    print("✅ Бот запущен. Автопостинг каждые 1.5 часа.")
    asyncio.create_task(scheduler())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
