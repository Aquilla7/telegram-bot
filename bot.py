import os
import asyncio
import aiohttp
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
PLAYLIST_URL = os.getenv("PLAYLIST_URL")

# прокси (если нужно)
PROXY_HOST = os.getenv("PROXY_HOST")
PROXY_PORT = os.getenv("PROXY_PORT")
PROXY_USER = os.getenv("PROXY_USER")
PROXY_PASS = os.getenv("PROXY_PASS")

PROXY_URL = None
if PROXY_HOST and PROXY_PORT:
    if PROXY_USER and PROXY_PASS:
        PROXY_URL = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"
    else:
        PROXY_URL = f"http://{PROXY_HOST}:{PROXY_PORT}"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- парсер ссылок видео из плейлиста VK ---
def get_vk_video_links(playlist_url):
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(playlist_url, headers=headers, proxies={"http": PROXY_URL, "https": PROXY_URL})
    soup = BeautifulSoup(r.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        if "vkvideo.ru/video" in a["href"]:
            full_link = a["href"]
            if not full_link.startswith("http"):
                full_link = "https://vkvideo.ru" + full_link
            links.append(full_link.split("?")[0])
    return list(set(links))

# --- получение прямых ссылок через SaveFrom ---
async def get_direct_link(video_url):
    api_url = "https://worker.savefrom.net/api/convert"
    payload = {"url": video_url}
    headers = {"User-Agent": "Mozilla/5.0"}

    async with aiohttp.ClientSession() as session:
        async with session.post(api_url, json=payload, headers=headers, proxy=PROXY_URL) as r:
            try:
                data = await r.json()
                return data["url"][0]["url"]
            except Exception:
                return None

# --- кнопка "опубликовать сейчас" ---
def admin_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Опубликовать сейчас", callback_data="publish_now")]
    ])
    return kb

# --- команда /start ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    if message.chat.type == "private":
        await message.answer("👋 Привет! Этот бот публикует видео из VK каждые 1.5 часа.",
                             reply_markup=admin_menu())

# --- публикация одного видео ---
async def publish_one_video():
    links = get_vk_video_links(PLAYLIST_URL)
    for url in links:
        direct = await get_direct_link(url)
        if direct:
            try:
                await bot.send_video(CHANNEL_ID, direct, caption='🎬 Видео от [@BillysFamily](https://t.me/billysbest)', parse_mode="Markdown")
                print(f"✅ Опубликовано: {url}")
                return
            except Exception as e:
                print(f"Ошибка при отправке: {e}")
    print("⚠️ Видео не найдено для публикации.")

# --- ручная публикация ---
@dp.callback_query(lambda c: c.data == "publish_now")
async def publish_now(callback: types.CallbackQuery):
    await callback.answer("Публикуем видео...")
    await publish_one_video()
    await callback.message.answer("✅ Видео опубликовано вручную.")

# --- автопостинг каждые 1.5 часа ---
async def auto_posting():
    while True:
        await publish_one_video()
        print("⏰ Следующая публикация через 1.5 часа...")
        await asyncio.sleep(5400)  # 1.5 часа

# --- запуск ---
async def main():
    asyncio.create_task(auto_posting())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
