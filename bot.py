import os
import asyncio
import aiohttp
import logging
import random
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv
import yt_dlp
import chromedriver_autoinstaller
import subprocess
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# ==========================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ==========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================
# ЗАГРУЗКА .ENV
# ==========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
VK_PLAYLIST_URL = os.getenv("VK_PLAYLIST_URL")

PROXY_USER = os.getenv("PROXY_USER")
PROXY_PASS = os.getenv("PROXY_PASS")
PROXY_IP = os.getenv("PROXY_IP")
PROXY_PORT = os.getenv("PROXY_PORT")

# ==========================
# ИНИЦИАЛИЗАЦИЯ БОТА
# ==========================
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# ==========================
# УСТАНОВКА CHROMIUM
# ==========================
CHROME_DIR = "/tmp/chrome"
CHROME_PATH = os.path.join(CHROME_DIR, "chrome-linux64", "chrome")

if not os.path.exists(CHROME_PATH):
    logger.info("⬇️ Скачиваю Chromium...")
    os.makedirs(CHROME_DIR, exist_ok=True)
    subprocess.run(
        "wget https://storage.googleapis.com/chromium-browser-snapshots/Linux_x64/1211495/chrome-linux64.zip -O /tmp/chrome.zip && unzip /tmp/chrome.zip -d /tmp/chrome",
        shell=True,
        check=True,
    )
else:
    logger.info("✅ Chromium уже установлен.")

chromedriver_autoinstaller.install()

# ==========================
# ЗАГРУЗКА СПИСКА ВИДЕО
# ==========================
async def fetch_vk_videos():
    proxy_url = f"socks5://{PROXY_USER}:{PROXY_PASS}@{PROXY_IP}:{PROXY_PORT}"
    ydl_opts = {
        "proxy": proxy_url,
        "extract_flat": True,
        "quiet": True,
        "skip_download": True,
        "extractor_args": {"vk": {"api": "auto"}}
    }

    logger.info(f"Используется прокси: {proxy_url}")
    logger.info(f"Используется плейлист: {VK_PLAYLIST_URL}")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(VK_PLAYLIST_URL, download=False)
        if "entries" in result:
            videos = [entry["url"] for entry in result["entries"] if "url" in entry]
            logger.info(f"Найдено видео в плейлисте: {len(videos)}")
            return videos
        else:
            logger.warning("Нет доступных видео в плейлисте.")
            return []
    except Exception as e:
        logger.error(f"Ошибка при получении плейлиста: {e}")
        return []

# ==========================
# ПУБЛИКАЦИЯ ВИДЕО
# ==========================
async def publish_video():
    logger.info("🚀 Автопубликация...")
    videos = await fetch_vk_videos()
    if not videos:
        await bot.send_message(CHANNEL_ID, "⚠️ Нет доступных видео или ошибка получения плейлиста.")
        return

    video_url = random.choice(videos)
    await bot.send_message(CHANNEL_ID, f"📹 Новое видео: {video_url}")

# ==========================
# ОБРАБОТЧИК КОМАНД
# ==========================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Опубликовать видео вне очереди", callback_data="publish_now")]
    ])
    await message.answer("Бот активен. Автопубликация каждые 1.5 часа.", reply_markup=kb)

@dp.callback_query(lambda c: c.data == "publish_now")
async def manual_publish(callback: types.CallbackQuery):
    await callback.answer("Публикую видео вне очереди...")
    await publish_video()
    await callback.message.answer("✅ Видео опубликовано вне очереди!")

# ==========================
# ЦИКЛ АВТОПУБЛИКАЦИИ
# ==========================
async def scheduler():
    while True:
        await publish_video()
        await asyncio.sleep(5400)  # каждые 1.5 часа

# ==========================
# ЗАПУСК
# ==========================
async def main():
    logger.info("🤖 Бот запущен. Автопостинг каждые 1.5 часа.")
    asyncio.create_task(scheduler())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
