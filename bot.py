import asyncio
import os
import random
import aiosqlite
import subprocess
import json
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
VK_PLAYLIST_URL = os.getenv("VK_PLAYLIST_URL", "").strip()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_PATH = "bot.db"
POST_INTERVAL = 90 * 60  # 1.5 часа
TMP_FILE = "video.mp4"
COOKIES_PATH = "cookies.txt"

# ---------- База ----------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS published_videos (
                id TEXT PRIMARY KEY,
                url TEXT
            )
        """)
        await db.commit()

# ---------- Клавиатура ----------
def admin_menu():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="📤 Опубликовать видео вне очереди"))
    return builder.as_markup(resize_keyboard=True)

# ---------- Получение списка видео через subprocess ----------
async def fetch_videos_from_vk():
    try:
        result = subprocess.run([
            "yt-dlp",
            "--cookies", COOKIES_PATH,
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "--no-warnings",
            "--flat-playlist",
            "-j",
            VK_PLAYLIST_URL
        ], capture_output=True, text=True)

        if result.returncode != 0:
            print("❌ Ошибка при запросе yt-dlp:", result.stderr)
            return []

        videos = []
        for line in result.stdout.splitlines():
            try:
                data = json.loads(line)
                url = data.get("url") or data.get("webpage_url")
                title = data.get("title", "Без названия")
                vid = data.get("id") or url
                if url:
                    if url.startswith("/video"):
                        url = "https://vkvideo.ru" + url
                    videos.append({"id": vid, "url": url, "title": title})
            except json.JSONDecodeError:
                continue

        print(f"📋 Найдено видео в плейлисте: {len(videos)}")
        return videos

    except Exception as e:
        print(f"❌ Ошибка при получении списка видео: {e}")
        return []

# ---------- Выбор следующего ----------
async def get_next_video():
    videos = await fetch_videos_from_vk()
    if not videos:
        return None

    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall("SELECT id FROM published_videos")
        published_ids = {r[0] for r in rows}

    for video in videos:
        if video["id"] not in published_ids:
            return video

    return random.choice(videos)

# ---------- Отправка видео ----------
async def publish_video():
    video = await get_next_video()
    if not video:
        print("⚠️ Нет доступных видео.")
        await notify_admins("⚠️ Нет доступных видео или ошибка получения плейлиста.")
        return False

    video_url = video["url"]
    caption = '<a href="https://t.me/billysbest">🎥 Видео от @BillysFamily</a>'

    try:
        if os.path.exists(TMP_FILE):
            os.remove(TMP_FILE)

        print(f"⬇️ Скачиваю: {video['title']} | {video_url}")
        result = subprocess.run([
            "yt-dlp",
            "--cookies", COOKIES_PATH,
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "-f", "best[ext=mp4][filesize<1900M]/best",
            "-o", TMP_FILE,
            video_url
        ], capture_output=True, text=True)

        if result.returncode != 0 or not os.path.exists(TMP_FILE):
            print("❌ Ошибка при скачивании:", result.stderr)
            await notify_admins("❌ Не удалось скачать видео. Возможно, куки устарели.")
            return False

        print("📤 Отправляю в канал файл:", TMP_FILE)
        with open(TMP_FILE, "rb") as f:
            await bot.send_video(CHANNEL_ID, f, caption=caption)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO published_videos (id, url) VALUES (?, ?)",
                (video["id"], video_url)
            )
            await db.commit()

        print("✅ Публикация успешна.")
        return True

    except Exception as e:
        print(f"❌ Ошибка при публикации: {e}")
        await notify_admins(f"❌ Ошибка при публикации: {e}")
        return False

    finally:
        if os.path.exists(TMP_FILE):
            os.remove(TMP_FILE)

# ---------- Уведомление админов ----------
async def notify_admins(text: str):
    for admin_id in ADMINS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass

# ---------- Планировщик ----------
async def scheduler():
    while True:
        print("⏰ Автопубликация...")
        await publish_video()
        print("🕒 Следующая попытка через 1.5 часа.")
        await asyncio.sleep(POST_INTERVAL)

# ---------- /start ----------
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    if message.from_user.id in ADMINS:
        await message.answer(
            "👋 Привет, админ!\nБот публикует видео каждые 1.5 часа.",
            reply_markup=admin_menu()
        )
    else:
        await message.answer("Этот бот предназначен только для администраторов.")

# ---------- Ручная публикация ----------
@dp.message(lambda m: m.text == "📤 Опубликовать видео вне очереди")
async def manual_publish(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("🚀 Публикую следующее видео...")
    ok = await publish_video()
    await message.answer("✅ Готово!" if ok else "⚠️ Не удалось опубликовать.")

# ---------- Запуск ----------
async def main():
    await init_db()
    print(f"🎬 Используется плейлист: {VK_PLAYLIST_URL}")
    asyncio.create_task(scheduler())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
