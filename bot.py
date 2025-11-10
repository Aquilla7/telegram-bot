import asyncio
import os
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
import yt_dlp

# === Загрузка токена и переменных ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
ADMINS = [int(x) for x in os.getenv("ADMINS", "0").split(",") if x != "0"]
VK_PLAYLIST_URL = os.getenv("VK_PLAYLIST_URL")  # добавь в .env ссылку на плейлист

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# === Инициализация базы данных ===
async def init_db():
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS published_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE
            )
        """)
        await db.commit()

# === Меню администратора ===
def admin_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📤 Опубликовать сейчас")]
        ],
        resize_keyboard=True
    )

# === Команда /start ===
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    if message.from_user.id in ADMINS:
        await message.answer("👋 Привет, админ! Меню управления:", reply_markup=admin_menu())
    else:
        await message.answer("Привет! У тебя нет прав администратора.")

# === Скачивание видео из VK ===
async def download_next_video():
    async with aiosqlite.connect("bot.db") as db:
        # загружаем уже опубликованные ссылки
        cur = await db.execute("SELECT url FROM published_videos")
        published = [row[0] for row in await cur.fetchall()]

    ydl_opts = {"quiet": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        playlist = ydl.extract_info(VK_PLAYLIST_URL, download=False)
        if not playlist or "entries" not in playlist:
            return None
        for entry in playlist["entries"]:
            if entry["url"] not in published:
                return f"https://vk.com/video{entry['url']}"
    return None

# === Публикация видео ===
async def publish_video():
    video_url = await download_next_video()
    if not video_url:
        print("✅ Все видео из плейлиста уже опубликованы.")
        return

    try:
        ydl_opts = {"format": "mp4", "outtmpl": "video.mp4"}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            file_path = ydl.prepare_filename(info)

        caption = '🎬 @<a href="https://t.me/billysbest">BillysFamily</a>'
        await bot.send_video(CHANNEL_ID, video=open(file_path, "rb"), caption=caption)

        # сохраняем в БД, чтобы не публиковать повторно
        async with aiosqlite.connect("bot.db") as db:
            await db.execute("INSERT OR IGNORE INTO published_videos (url) VALUES (?)", (video_url,))
            await db.commit()

        os.remove(file_path)
        print(f"✅ Опубликовано: {video_url}")
    except Exception as e:
        print("⚠️ Ошибка при публикации видео:", e)

# === Цикл автопостинга ===
async def auto_post_loop():
    await asyncio.sleep(5)
    while True:
        await publish_video()
        await asyncio.sleep(5400)  # 1.5 часа

# === Кнопка "Опубликовать сейчас" ===
@dp.message(F.text == "📤 Опубликовать сейчас")
async def manual_post(message: types.Message):
    if message.from_user.id not in ADMINS:
        return await message.answer("⛔ Нет прав.")
    await message.answer("⏳ Публикую следующее видео...")
    await publish_video()
    await message.answer("✅ Видео опубликовано!")

# === Запуск ===
async def main():
    await init_db()
    asyncio.create_task(auto_post_loop())
    print("✅ Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
