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

DB_PATH = "bot.db"
POST_INTERVAL = 90 * 60  # 1.5 часа
TMP_FILE = "video.mp4"
COOKIES_PATH = "cookies.txt"  # положи сюда cookies, если плейлист приватный


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


# ---------- Вспомогательное: опции yt-dlp ----------
def yd_opts_common(download: bool):
    """
    Общие опции yt-dlp. Если download=True — на скачивание файла,
    иначе — на получение метаданных.
    """
    opts = {
        "quiet": True,
        "extract_flat": False,  # нужно для реальных ссылок и форматов
        "noplaylist": False,
        "retries": 10,
        "socket_timeout": 20,
        "http_headers": {
            # иногда помогает vkvideo отдать поток
            "User-Agent":
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        },
    }
    # если есть cookies.txt — используем (обычно не нужно для публичных плейлистов)
    if os.path.exists(COOKIES_PATH):
        opts["cookiefile"] = COOKIES_PATH

    if download:
        # Стараемся взять MP4/H264/AAC, и ограничить размер, чтобы < 2GB
        # Без ffmpeg: запрещаем ремаксы и берём готовые mp4
        opts.update({
            "outtmpl": TMP_FILE,
            "format":
                # лучший mp4-видео + m4a-аудио, оба < 1.9 ГБ
                "bv*[ext=mp4][filesize<1900M]+ba[ext=m4a]/"
                # либо одиночный mp4 до 1.9 ГБ
                "b[ext=mp4][filesize<1900M]/"
                # fallback: любой лучший ≤ 1.9 ГБ
                "best[filesize<1900M]/best",
            "concurrent_fragment_downloads": 5,
        })
    return opts


# ---------- Получение списка видео из плейлиста ----------
async def fetch_videos_from_vk():
    try:
        with YoutubeDL(yd_opts_common(download=False)) as ydl:
            info = ydl.extract_info(VK_VIDEO_URL, download=False)

        entries = info.get("entries") or []
        if not entries:
            print("⚠️ Плейлист пуст или недоступен. URL:", VK_VIDEO_URL)
            return []

        videos = []
        for v in entries:
            # Вытаскиваем URL страницы видео
            url = v.get("webpage_url") or v.get("original_url") or v.get("url")
            if not url:
                continue
            # Нормализуем относительные ссылки
            if url.startswith("/video"):
                url = "https://vkvideo.ru" + url
            title = v.get("title") or "Видео без названия"
            vid = v.get("id") or url
            videos.append({"id": vid, "url": url, "title": title})

        print(f"📋 Найдено видео в плейлисте: {len(videos)}")
        if videos:
            print("🔗 Пример URL:", videos[0]["url"])
        return videos

    except Exception as e:
        print(f"❌ Ошибка при загрузке списка видео: {e}")
        return []


# ---------- Выбор следующего ----------
async def get_next_video():
    videos = await fetch_videos_from_vk()
    if not videos:
        return None

    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall("SELECT id FROM published_videos")
        published_ids = {r[0] for r in rows}

    # первое ещё не публиковавшееся
    for video in videos:
        if video["id"] not in published_ids:
            return video

    # если всё уже было, крутим по кругу
    return random.choice(videos)


# ---------- Отправка видео ----------
async def publish_video():
    video = await get_next_video()
    if not video:
        print("⚠️ Нет доступных видео (список пуст/недоступен).")
        await notify_admins("⚠️ Нет доступных видео или ошибка получения плейлиста.")
        return False

    video_url = video["url"]
    caption = '<a href="https://t.me/billysbest">🎥 Видео от @BillysFamily</a>'

    # 1) Всегда скачиваем файл (vkvideo не даёт прямой mp4 по URL страницы)
    try:
        if os.path.exists(TMP_FILE):
            try:
                os.remove(TMP_FILE)
            except Exception:
                pass

        print(f"⬇️  Скачиваю: {video['title']} | {video_url}")
        with YoutubeDL(yd_opts_common(download=True)) as ydl:
            res = ydl.extract_info(video_url, download=True)
            # диагностические принты по формату
            chosen = res.get("requested_formats") or ([res] if res else [])
            for i, fmt in enumerate(chosen):
                fext = fmt.get("ext")
                fsize = fmt.get("filesize") or fmt.get("filesize_approx")
                print(f"   · формат[{i}]: ext={fext}, size={fsize}")

        if not os.path.exists(TMP_FILE):
            print("❌ Файл не скачался (нет video.mp4).")
            await notify_admins("❌ Файл не скачался — возможно, нужны cookies или видео слишком большое.")
            return False

        # 2) Отправляем файл
        print("📤 Отправляю в канал файл:", TMP_FILE)
        with open(TMP_FILE, "rb") as f:
            await bot.send_video(CHANNEL_ID, f, caption=caption)

        # 3) Сохраняем в БД как опубликованное
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
        # Чистим временный файл
        try:
            if os.path.exists(TMP_FILE):
                os.remove(TMP_FILE)
        except Exception:
            pass


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
        print("⏰ Запуск автоматической публикации...")
        await publish_video()
        print("🕒 Следующая попытка через 1.5 часа.")
        await asyncio.sleep(POST_INTERVAL)


# ---------- /start ----------
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    if message.from_user.id in ADMINS:
        await message.answer(
            "👋 Привет, админ!\n"
            "Бот публикует видео из плейлиста каждые 1.5 часа.",
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
    print(f"🎬 Используется плейлист: {VK_VIDEO_URL}")
    asyncio.create_task(scheduler())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
