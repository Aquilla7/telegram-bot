import asyncio
import os
import random
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from dotenv import load_dotenv
from yt_dlp import YoutubeDL

# === Загрузка переменных окружения ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
ADMINS = [int(x) for x in os.getenv("ADMINS", "").split(",") if x]
VK_VIDEO_URL = os.getenv("VK_PLAYLIST_URL", "").strip()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# === Инициализация базы данных ===
async def init_db():
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS published_videos (
                id TEXT PRIMARY KEY,
                url TEXT
            )
        """)
        await db.commit()

# === Клавиатура администратора ===
def admin_menu():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="📤 Опубликовать видео вне очереди"))
    return builder.as_markup(resize_keyboard=True)

# === Получение видео с VK ===
async def fetch_videos_from_vk():
    try:
        ydl_opts = {
            "quiet": True,
            "extract_flat": False,  # важно: реальные ссылки
        }
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(VK_VIDEO_URL, download=False)
            entries = info.get("entries") or []
            if not entries:
                print("⚠️ Плейлист пуст или недоступен.")
                return []

            videos = []
            for v in entries:
                url = v.get("webpage_url") or v.get("url")
                if not url:
                    continue
                if url.startswith("/video"):
                    url = "https://vkvideo.ru" + url
                title = v.get("title") or "Видео без названия"
                vid = v.get("id") or url
                videos.append({"id": vid, "url": url, "title": title})
            print(f"📋 Найдено {len(videos)} видео.")
            if videos:
                print("🔗 Пример URL:", videos[0]["url"])
            return videos
    except Exception as e:
        print(f"❌ Ошибка при загрузке списка видео: {e}")
        return []

# === Получить следующее видео ===
async def get_next_video():
    videos = await fetch_videos_from_vk()
    if not videos:
        return None

    async with aiosqlite.connect("bot.db") as db:
        published = await db.execute_fetchall("SELECT id FROM published_videos")
        published_ids = {row[0] for row in published}

    for video in videos:
        if video["id"] not in published_ids:
            return video
    return random.choice(videos)

# === Публикация видео ===
async def publish_video():
    video = await get_next_video()
    if not video:
        print("⚠️ Нет новых видео или ошибка при получении списка.")
        await notify_admins("⚠️ Ошибка при публикации видео или нет доступных видео.")
        return False

    video_url = video["url"]
    caption = '<a href="https://t.me/billysbest">🎥 Видео от @BillysFamily</a>'

    try:
        print(f"📤 Отправляю по URL: {video_url}")
        await bot.send_video(CHANNEL_ID, video=video_url, caption=caption)
        print("✅ Отправлено по URL.")
    except Exception as e:
        print(f"Не удалось по URL ({e}), пробую скачать файл...")
        try:
            ydl_opts = {
                "outtmpl": "video.mp4",
                "format": "best[filesize<1900M]/best",
                "quiet": True,
            }
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            with open("video.mp4", "rb") as f:
                await bot.send_video(CHANNEL_ID, f, caption=caption)
            os.remove("video.mp4")
        except Exception as e2:
            print(f"❌ Ошибка при отправке: {e2}")
            await notify_admins("⚠️ Ошибка при публикации видео или нет доступных видео.")
            return False

    async with aiosqlite.connect("bot.db") as db:
        await db.execute("INSERT OR REPLACE INTO published_videos (id, url) VALUES (?, ?)",
                         (video["id"], video_url))
        await db.commit()
    return True

# === Уведомление админов ===
async def notify_admins(text):
    for admin_id in ADMINS:
        try:
            await bot.send_message(admin_id, text)
        except:
            pass

# === Автопостинг каждые 1.5 часа ===
async def scheduler():
    while True:
        print("⏰ Проверяю новые видео...")
        await publish_video()
        print("🕒 Следующая публикация через 1.5 часа.")
        await asyncio.sleep(5400)

# === Команда /start ===
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    if message.from_user.id in ADMINS:
        await message.answer("👋 Привет, админ!", reply_markup=admin_menu())
    else:
        await message.answer("Этот бот предназначен только для администраторов.")

# === Ручная публикация ===
@dp.message(lambda m: m.text == "📤 Опубликовать видео вне очереди")
async def manual_publish(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("🚀 Публикую видео...")
    success = await publish_video()
    if success:
        await message.answer("✅ Видео опубликовано!")
    else:
        await message.answer("⚠️ Ошибка при публикации видео или нет доступных видео.")

# === Запуск ===
async def main():
    await init_db()
    print(f"🎬 Использую плейлист: {VK_VIDEO_URL}")
    asyncio.create_task(scheduler())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
