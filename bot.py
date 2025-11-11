import asyncio
import logging
import os
import time
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from yt_dlp import YoutubeDL
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import chromedriver_autoinstaller

# ===== Автоматическая установка ChromeDriver =====
chromedriver_autoinstaller.install()

# ===== Настройки =====
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
VK_PLAYLIST_URL = os.getenv("VK_PLAYLIST_URL")
PROXY_URL = os.getenv("PROXY_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)


# ===== Получение cookies через Chromium =====
def get_vk_cookies():
    try:
        logging.info("🌐 Запуск headless Chromium для получения cookies...")
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--ignore-certificate-errors")

        if PROXY_URL and PROXY_URL.startswith("socks5://"):
            proxy_clean = PROXY_URL.replace("socks5://", "")
            options.add_argument(f"--proxy-server=socks5://{proxy_clean}")
            logging.info(f"🧩 Используется прокси: {proxy_clean}")

        driver = webdriver.Chrome(options=options)
        driver.get("https://vkvideo.ru")
        time.sleep(5)
        cookies = driver.get_cookies()
        driver.quit()

        cookies_dict = {c["name"]: c["value"] for c in cookies}
        logging.info(f"🍪 Получено cookies: {len(cookies_dict)}")
        return cookies_dict
    except Exception as e:
        logging.error(f"Ошибка при получении cookies: {e}")
        return {}


# ===== Настройки yt-dlp =====
def build_ydl_opts(cookies):
    return {
        "proxy": PROXY_URL,
        "geo_bypass": True,
        "nocheckcertificate": True,
        "quiet": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0 Safari/537.36",
            "Accept-Language": "ru,en-US;q=0.8,en;q=0.5",
            "Referer": "https://vkvideo.ru/",
        },
        "cookies": cookies,
    }


# ===== Получение списка видео =====
async def get_video_list(cookies):
    try:
        with YoutubeDL(build_ydl_opts(cookies)) as ydl:
            info = ydl.extract_info(VK_PLAYLIST_URL, download=False)
            return info.get("entries", [])
    except Exception as e:
        logging.error(f"Ошибка при получении списка видео: {e}")
        return []


# ===== Скачивание видео =====
async def download_video(url, cookies):
    try:
        opts = build_ydl_opts(cookies)
        opts.update({"outtmpl": "video.%(ext)s"})
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)
    except Exception as e:
        logging.error(f"Ошибка при скачивании видео: {e}")
        return None


# ===== Публикация видео =====
async def publish_video():
    cookies = get_vk_cookies()
    videos = await get_video_list(cookies)

    if not videos:
        await bot.send_message(CHANNEL_ID, "⚠️ Нет доступных видео или ошибка получения плейлиста.")
        return

    first_video = videos[0]
    video_url = first_video.get("url") or first_video.get("webpage_url")
    title = first_video.get("title", "Без названия")

    logging.info(f"⬇️ Скачиваю видео: {title} | {video_url}")
    video_file = await download_video(video_url, cookies)
    if not video_file:
        await bot.send_message(CHANNEL_ID, "⚠️ Не удалось скачать видео.")
        return

    logging.info("📤 Отправляю видео в канал...")
    with open(video_file, "rb") as f:
        await bot.send_video(CHANNEL_ID, video=f, caption=f"🎥 {title}")

    os.remove(video_file)


# ===== Автопубликация =====
async def auto_publish():
    while True:
        logging.info("🔁 Автопубликация...")
        await publish_video()
        await asyncio.sleep(5400)  # 1.5 часа


# ===== Команды =====
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 Опубликовать видео вне очереди", callback_data="publish_now")]
        ]
    )
    await message.answer("Бот запущен! Публикация каждые 1.5 часа.", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data == "publish_now")
async def publish_now(callback_query: types.CallbackQuery):
    await callback_query.message.answer("🚀 Публикую видео вне очереди...")
    await publish_video()
    await callback_query.answer("Готово!")


# ===== Запуск =====
async def main():
    logging.info(f"🎬 Плейлист: {VK_PLAYLIST_URL}")
    logging.info(f"🌐 Прокси: {PROXY_URL}")
    asyncio.create_task(auto_publish())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
