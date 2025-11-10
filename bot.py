import asyncio
import aiohttp
import aiosqlite
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from yt_dlp import YoutubeDL

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
VK_VIDEO_URL = "https://vkvideo.ru/@pruzankin/added"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

DB_PATH = "bot.db"
POST_INTERVAL = 90 * 60  # 1.5 часа


# ---------- Создание базы ----------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS published_videos (id TEXT PRIMARY KEY)"
        )
        await db.commit()


# ---------- Получение видео со страницы VKVideo ----------
async def fetch_videos_from_vk():
    try:
        ydl_opts = {"quiet": True, "extract_flat": True, "force_generic_extractor": True}
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(VK_VIDEO_URL, download=False)
            if "entries" not in info or not info["entries"]:
                return []
            videos = [
                {"id": v["id"], "url": v["url"], "title": v.get("title", "Видео без названия")}
                for v in info["entries"]
                if v.get("url")
            ]
            return videos
    except Exception as e:
        print(f"Ошибка при загрузке списка видео: {e}")
        return []


# ---------- Получение следующего видео для публикации ----------
async def get_next_video():
    videos = await fetch_videos_from_vk()
    if not videos:
        return None

    async with aiosqlite.connect(DB_PATH) as db:
        for video in videos:
            cursor = await db.execute("SELECT id FROM published_videos WHERE id = ?", (video["id"],))
            exists = await cursor.fetchone()
            if not exists:
                await db.execute("INSERT INTO published_videos (id) VALUES (?)", (video["id"],))
                await db.commit()
                return video

        # если все видео уже опубликованы — начинаем заново
        await db.execute("DELETE FROM published_videos")
        await db.commit()
        return videos[0]


# ---------- Публикация видео ----------
async def publish_video():
    video = await get_next_video()
    if not video:
        return None

    video_url = video["url"]
    caption = '<a href="https://t.me/billysbest">🎥 Видео от @BillysFamily</a>'
    try:
        await bot.send_message(CHANNEL_ID, f"📤 Публикую видео: {video['title']}")

        ydl_opts = {"outtmpl": "video.mp4"}
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        with open("video.mp4", "rb") as file:
            await bot.send_video(CHANNEL_ID, file, caption=caption)

        os.remove("video.mp4")
        return True
    except Exception as e:
        print(f"Ошибка при отправке видео: {e}")
        return False


# ---------- Фоновая задача ----------
async def scheduler():
    while True:
        success = await publish_video()
        if success:
            print("✅ Видео опубликовано")
        else:
            print("⚠️ Ошибка при публикации видео или нет доступных видео.")
        await asyncio.sleep(POST_INTERVAL)


# ---------- Обработка команды /start ----------
@dp.message(Command("start"))
async def start(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.add(InlineKeyboardButton(text="📺 Опубликовать сейчас", callback_data="publish_now"))
    await message.answer("✅ Бот запущен.\nВидео публикуются каждые 1.5 часа.", reply_markup=kb.as_markup())


# ---------- Кнопка «Опубликовать сейчас» ----------
@dp.callback_query(lambda c: c.data == "publish_now")
async def publish_now(callback_query: types.CallbackQuery):
    await callback_query.answer("⏳ Публикую сейчас...")
    success = await publish_video()
    if success:
        await callback_query.message.answer("✅ Видео опубликовано!")
    else:
        await callback_query.message.answer("⚠️ Ошибка при публикации видео.")


# ---------- Главный запуск ----------
async def main():
    await init_db()
    asyncio.create_task(scheduler())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
