import asyncio
import os
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

# === Загружаем настройки из .env ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMINS = [int(x) for x in os.getenv("ADMINS", "0").split(",") if x.strip() and x != "0"]
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

# === Инициализация бота ===
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# === Инициализация базы данных ===
async def init_db():
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                text TEXT,
                video_path TEXT
            )
        """)
        await db.commit()

# === Клавиатура администратора ===
def admin_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📝 Создать пост")],
        ],
        resize_keyboard=True,
    )

# === Команда /start ===
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    if message.from_user.id in ADMINS:
        await message.answer("👋 Привет, админ!", reply_markup=admin_menu())
    else:
        await message.answer("⛔ У вас нет прав администратора.")

# === Создание поста (ожидаем видео) ===
drafts = {}

@dp.message(F.text == "📝 Создать пост")
async def create_post(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    drafts[message.from_user.id] = {"stage": "waiting_video"}
    await message.answer("🎬 Отправь видео, которое хочешь опубликовать (можно с подписью).")

@dp.message(F.video)
async def got_video(message: types.Message):
    uid = message.from_user.id
    if uid not in drafts or drafts[uid].get("stage") != "waiting_video":
        return

    # Сохраняем видео локально
    file = await bot.get_file(message.video.file_id)
    os.makedirs("videos", exist_ok=True)
    path = f"videos/{message.video.file_unique_id}.mp4"
    await bot.download_file(file.file_path, path)

    # Текст поста (caption)
    text = message.caption or ""

    # Клавиатура подтверждения
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Опубликовать", callback_data="publish_video")],
            [InlineKeyboardButton(text="🗑 Отменить", callback_data="cancel")],
        ]
    )

    drafts[uid] = {"stage": "ready", "video_path": path, "text": text}
    await message.answer("📋 Готово! Опубликовать это видео?", reply_markup=kb)

# === Публикация видео с нативными реакциями ===
@dp.callback_query(F.data == "publish_video")
async def publish(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid not in drafts or drafts[uid].get("stage") != "ready":
        return

    text = drafts[uid]["text"]
    video_path = drafts[uid]["video_path"]

    try:
        msg = await bot.send_video(
            chat_id=CHANNEL_ID,
            video=FSInputFile(video_path),
            caption=text
        )
    except Exception as e:
        await callback.message.answer(f"⚠️ Ошибка при отправке видео: {e}")
        return

    # Сохраняем в базу
    async with aiosqlite.connect("bot.db") as db:
        await db.execute(
            "INSERT INTO posts (message_id, text, video_path) VALUES (?, ?, ?)",
            (msg.message_id, text, video_path),
        )
        await db.commit()

    drafts.pop(uid, None)
    await callback.message.edit_text("✅ Пост опубликован в канале!")

# === Отмена публикации ===
@dp.callback_query(F.data == "cancel")
async def cancel(callback: types.CallbackQuery):
    drafts.pop(callback.from_user.id, None)
    await callback.message.edit_text("🚫 Черновик удалён.")

# === Запуск ===
async def main():
    await init_db()
    print("✅ Бот запущен. Видео публикуются с нативными реакциями Telegram.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
