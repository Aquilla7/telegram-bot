import os
import asyncio
import aiohttp
import logging
import random
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
import yt_dlp

# ==========================
# ЛОГИРОВАНИЕ
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

# ==========================
# ПРОКСИ НАСТРОЙКИ
# ==========================
PROXY_USER = "VGRNRd"
PROXY_PASS = "0BVZC4"
PROXY_HOST = "147.45.38.23"
PROXY_PORT = "8000"

PROXIES = [
    f"socks5://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}",
    f"https://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}",
    None,  # без прокси
]

# ==========================
# НАСТРОЙКА БОТА
# ==========================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ==========================
# ПРОВЕРКА ПРОКСИ
# ==========================
async def find_working_proxy():
    """Перебирает варианты и возвращает первый рабочий прокси"""
    for proxy in PROXIES:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://vkvideo.ru", proxy=proxy, timeout=10) as resp:
                    if resp.status == 200:
                        logger.info(f"✅ Рабочее соединение найдено: {proxy or 'без прокси'}")
                        return proxy
        except Exception as e:
            logger.warning(f"⚠️ Прокси не подошёл: {proxy} — {e}")
    logger.error("❌ Ни один вариант соединения не сработал.")
    return None

# ==========================
# ЗАГРУЗКА СПИСКА ВИДЕО
# ==========================
async def fetch_vk_videos(proxy_url):
    cookie_file = "cookies.txt"
    ydl_opts = {
        "proxy": proxy_url,
        "extract_flat": True,
        "quiet": True,
        "skip_download": True,
    }

    if os.path.exists(cookie_file):
        ydl_opts["cookiefile"] = cookie_file
        logger.info("🍪 Используется cookies.txt для авторизации VK.")

    logger.info(f"📡 Используется прокси: {proxy_url or 'без прокси'}")
    logger.info(f"🎞️ Используется плейлист: {VK_PLAYLIST_URL}")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(VK_PLAYLIST_URL, download=False)

        if "entries" in result:
            videos = [e["url"] for e in result["entries"] if "url" in e]
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
async def publish_video(proxy_url):
    logger.info("🚀 Автопубликация...")
    videos = await fetch_vk_videos(proxy_url)
    if not videos:
        await bot.send_message(CHANNEL_ID, "⚠️ Нет доступных видео или ошибка получения плейлиста.")
        return
    video_url = random.choice(videos)
    await bot.send_message(CHANNEL_ID, f"📹 Новое видео: {video_url}")

# ==========================
# КОМАНДЫ
# ==========================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Опубликовать видео вне очереди", callback_data="publish_now")]
    ])
    await message.answer("🤖 Бот активен. Автопубликация каждые 1.5 часа.", reply_markup=kb)

@dp.callback_query(lambda c: c.data == "publish_now")
async def manual_publish(callback: types.CallbackQuery):
    await callback.answer("Публикую видео вне очереди...")
    await publish_video(callback.bot.proxy_url)
    await callback.message.answer("✅ Видео опубликовано вне очереди!")

# ==========================
# ПЛАНИРОВАНИЕ АВТОПОСТИНГА
# ==========================
async def scheduler(proxy_url):
    while True:
        await publish_video(proxy_url)
        await asyncio.sleep(5400)  # 1.5 часа

# ==========================
# ЗАПУСК
# ==========================
async def main():
    logger.info("🤖 Бот запущен. Поиск рабочего соединения...")
    proxy_url = await find_working_proxy()

    if not proxy_url:
        logger.error("🚫 Не найдено рабочее соединение. Завершение работы.")
        return

    asyncio.create_task(scheduler(proxy_url))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
