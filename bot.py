import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from yt_dlp import YoutubeDL
from dotenv import load_dotenv

# ======================= НАСТРОЙКА =======================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
VK_PLAYLIST_URL = os.getenv("VK_PLAYLIST_URL")
PROXY_URL = os.getenv("PROXY_URL")
COOKIES_PATH = "cookies.txt"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)

# ======================= YT-DLP НАСТРОЙКИ =======================
YDL_BASE = {
    "cookiefile": COOKIES_PATH,
    "proxy": PROXY_URL,
    "geo_bypass": True,
    "nocheckcertificate": True,
    "quiet": True,
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
        "Gecko/20100101 Firefox/121.0"
    ),
    "http_headers": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru,en-US;q=0.8,en;q=0.5",
        "Referer": "https://vkvideo.ru/",
        "Origin": "https://vkvideo.ru",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    },
    "extractor_args": {
        "generic": {"player_client": ["html5"]},
    },
}

# ======================= ФУНКЦИИ =======================
async def get_video_list():
    try:
        with YoutubeDL(YDL_BASE) as ydl:
            info = ydl.extract_info(VK_PLAYLIST_URL, download=False)
            if "_entries" in info:
                videos = info["_entries"]
            elif "entries" in info:
                videos = info["entries"]
            else:
                videos = []
            return videos
    except Exception as e:
        logging.error(f"Ошибка при получении плейлиста: {e}")
        return []

async def download_video(url):
    try:
        opts = YDL_BASE.copy()
        opts.update({"outtmpl": "video.%(ext)s", "quiet": True})
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return filename
    except Exception as e:
        logging.error(f"Ошибка при скачивании видео: {e}")
        return None

async def publish_video():
    try:
        videos = await get_video_list()
        if not videos:
            await bot.send_message(CHANNEL_ID, "⚠️ Нет доступных видео или ошибка получения плейлиста.")
            return

        first_video = videos[0]
        video_url = first_video.get("url") or first_video.get("webpage_url")
        title = first_video.get("title", "Без названия")

        logging.info(f"⬇️ Скачиваю видео: {title} | {video_url}")
        video_file = await download_video(video_url)

        if not video_file:
            await bot.send_message(CHANNEL_ID, "⚠️ Не удалось скачать видео.")
            return

        logging.info("📤 Отправляю видео в канал...")
        with open(video_file, "rb") as f:
            await bot.send_video(CHANNEL_ID, video=f, caption=f"🎥 {title}")

        os.remove(video_file)

    except Exception as e:
        logging.error(f"Ошибка при публикации видео: {e}")
        await bot.send_message(CHANNEL_ID, "⚠️ Ошибка при публикации видео или нет доступных видео.")

# ======================= АВТОПУБЛИКАЦИЯ =======================
async def auto_publish():
    while True:
        logging.info("🔁 Автопубликация...")
        await publish_video()
        await asyncio.sleep(5400)  # 1.5 часа

# ======================= КОМАНДЫ =======================
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 Опубликовать видео вне очереди", callback_data="publish_now")]
        ]
    )
    await message.answer("Привет! Бот запущен и готов публиковать видео каждые 1.5 часа.", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data == "publish_now")
async def publish_now(callback_query: types.CallbackQuery):
    await callback_query.message.answer("🚀 Публикую видео вне очереди...")
    await publish_video()
    await callback_query.answer("Видео опубликовано!")

# ======================= ЗАПУСК =======================
async def main():
    logging.info(f"🎬 Используется плейлист: {VK_PLAYLIST_URL}")
    logging.info(f"🌐 Используется прокси: {PROXY_URL}")
    asyncio.create_task(auto_publish())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
