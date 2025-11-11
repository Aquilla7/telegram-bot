import asyncio
import os
import random
import aiosqlite
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

# Базовые опции для yt-dlp (важно: cookiefile + заголовки)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:119.0) Gecko/20100101 Firefox/119.0"
YDL_BASE = {
    "cookiefile": COOKIES_PATH,
    "user_agent": UA,
    "http_headers": {
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://vkvideo.ru/",
        "Origin": "https://vkvideo.ru",
    },
    "quiet": True,
    "nocheckcertificate": True,  # на случай, если у провайдера цепочка криво отдается
}

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

# ---------- Получение списка видео через yt-dlp (Python API) ----------
async def fetch_videos_from_vk():
    try:
        # extract_flat — получаем плоский список без скачивания
        opts = {**YDL_BASE, "extract_flat": "in_playlist", "skip_download": True}
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(VK_PLAYLIST_URL, download=False)

        # Если плейлист вернул редирект/пусто — info может быть None
        if not info:
            print("❌ yt-dlp вернул пустой результат (возможно, куки не приняты)")
            return []

        # Унифицируем структуру: у плейлиста обычно есть 'entries'
        entries = info.get("entries") or []
        videos = []
        for it in entries:
            # Для extract_flat yt-dlp обычно отдает url/id/title на уровне элемента
            url = it.get("url") or it.get("webpage_url")
            vid = it.get("id") or url
            title = it.get("title") or "Без названия"

            if not url:
                continue
            # Иногда приходит относительный путь вида /video-... — нормализуем
            if url.startswith("/video"):
                url = "https://vkvideo.ru" + url

            videos.append({"id": vid, "url": url, "title": title})

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

    # берем первое непубликованное; если все были — вернем случайное
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
        opts = {
            **YDL_BASE,
            "format": "best[ext=mp4][filesize<1900M]/best",
            "outtmpl": TMP_FILE,
        }
        with YoutubeDL(opts) as ydl:
            ydl.download([video_url])

        if not os.path.exists(TMP_FILE):
            print("❌ Файл не появился после скачивания")
            await notify_admins("❌ Не удалось скачать видео. Возможно, cookies устарели.")
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
