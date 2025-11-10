import asyncio
import os
import aiosqlite
import yt_dlp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

# === Загружаем настройки из .env ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMINS = [int(x) for x in os.getenv("ADMINS", "0").split(",") if x.strip() and x != "0"]
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
VK_PLAYLIST_URL = os.getenv("VK_PLAYLIST_URL", "").strip()

# === Инициализация бота ===
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
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

# === Очистка базы (однократно) ===
async def clear_published_videos_once():
    flag_file = "cleared.flag"
    if os.path.exists(flag_file):
        print("⏩ Очистка пропущена (уже выполнена ранее).")
        return
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("DELETE FROM published_videos")
        await db.commit()
    with open(flag_file, "w") as f:
        f.write("done")
    print("🧹 Таблица published_videos успешно очищена!")

# === Получение следующего видео из VK ===
async def get_next_video():
    async with aiosqlite.connect("bot.db") as db:
        cur = await db.execute("SELECT url FROM published_videos")
        published = [r[0] for r in await cur.fetchall()]

    ydl_opts = {"quiet": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(VK_PLAYLIST_URL, download=False)
        for entry in info.get("entries", []):
            url = f"https://vk.com/video{entry['url']}"
            if url not in published:
                return url
    return None

# === Публикация видео ===
async def publish_video():
    video_url = await get_next_video()
    if not video_url:
        print("📭 Нет новых видео для публикации.")
        return False

    try:
        os.makedirs("videos", exist_ok=True)
        file_path = "videos/video.mp4"
        print(f"🎬 Скачиваю: {video_url}")

        ydl_opts = {"outtmpl": file_path, "quiet": True, "format": "best"}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        caption = f"🎥 Видео от <a href='https://t.me/billysbest'>@BillysFamily</a>"
        await bot.send_video(CHANNEL_ID, video=FSInputFile(file_path), caption=caption)

        async with aiosqlite.connect("bot.db") as db:
            await db.execute("INSERT OR IGNORE INTO published_videos (url) VALUES (?)", (video_url,))
            await db.commit()

        os.remove(file_path)
        print(f"✅ Опубликовано: {video_url}")
        return True
    except Exception as e:
        print(f"⚠️ Ошибка при публикации видео: {e}")
        return False

# === Цикл автопостинга ===
async def auto_post_loop():
    await asyncio.sleep(5)
    while True:
        await publish_video()
        print("⏰ Следующая публикация через 1.5 часа...")
        await asyncio.sleep(5400)

# === Команда /start ===
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    if message.from_user.id in ADMINS:
        kb = types.ReplyKeyboardMarkup(
            keyboard=[[types.KeyboardButton(text="📤 Опубликовать видео вне очереди")]],
            resize_keyboard=True
        )
        await message.answer("👋 Привет, админ!\nБот публикует видео каждые 1.5 часа.", reply_markup=kb)
    else:
        await message.answer("Привет! У тебя нет прав администратора.")

# === Обработка кнопки "Опубликовать вне очереди" ===
@dp.message(F.text == "📤 Опубликовать видео вне очереди")
async def manual_publish(message: types.Message):
    if message.from_user.id not in ADMINS:
        return await message.answer("⛔ У вас нет прав.")
    await message.answer("⏳ Публикую следующее видео из плейлиста...")
    result = await publish_video()
    if result:
        await message.answer("✅ Видео опубликовано!")
    else:
        await message.answer("⚠️ Новых видео нет или произошла ошибка.")

# === Запуск ===
async def main():
    await init_db()
    await clear_published_videos_once()
    asyncio.create_task(auto_post_loop())
    print("✅ Бот запущен. Автопостинг каждые 1.5 часа.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
