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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                text TEXT,
                status TEXT DEFAULT 'pending'
            )
        """)
        await db.commit()

# === Клавиатура администратора ===
def admin_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📝 Создать пост")],
            [types.KeyboardButton(text="📬 Предложения пользователей")],
        ],
        resize_keyboard=True,
    )

# === Команда /start ===
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    if message.from_user.id in ADMINS:
        await message.answer("👋 Привет, админ!", reply_markup=admin_menu())
    else:
        await message.answer("👋 Привет! Отправь идею поста — администраторы её рассмотрят.")

# === Создание поста (теперь сразу ждёт видео) ===
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

@dp.callback_query(F.data == "publish_video")
async def publish(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid not in drafts or drafts[uid].get("stage") != "ready":
        return

    text = drafts[uid]["text"]
    video_path = drafts[uid]["video_path"]

    # Отправляем видео в канал
    msg = await bot.send_video(CHANNEL_ID, FSInputFile(video_path), caption=text)

    # Сохраняем в базу
    async with aiosqlite.connect("bot.db") as db:
        await db.execute(
            "INSERT INTO posts (message_id, text, video_path) VALUES (?, ?, ?)",
            (msg.message_id, text, video_path),
        )
        await db.commit()

    drafts.pop(uid, None)
    await callback.message.edit_text("✅ Пост опубликован в канале!")

@dp.callback_query(F.data == "cancel")
async def cancel(callback: types.CallbackQuery):
    drafts.pop(callback.from_user.id, None)
    await callback.message.edit_text("🚫 Черновик удалён.")

# === Предложения пользователей ===
@dp.message(F.text == "📬 Предложения пользователей")
async def show_proposals(message: types.Message):
    if message.from_user.id not in ADMINS:
        return

    async with aiosqlite.connect("bot.db") as db:
        cur = await db.execute("SELECT id, username, text FROM proposals WHERE status='pending'")
        rows = await cur.fetchall()

    if not rows:
        await message.answer("📭 Нет новых предложений.")
        return

    for pid, username, text in rows:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{pid}"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{pid}"),
                ]
            ]
        )
        nick = f"@{username}" if username else "аноним"
        await message.answer(f"📨 От {nick}:\n\n{text}", reply_markup=kb)

@dp.callback_query(F.data.startswith("approve_"))
async def approve(callback: types.CallbackQuery):
    pid = int(callback.data.split("_")[1])

    async with aiosqlite.connect("bot.db") as db:
        cur = await db.execute("SELECT text FROM proposals WHERE id=?", (pid,))
        row = await cur.fetchone()
        if not row:
            await callback.answer("Не найдено.")
            return
        text = row[0]
        await db.execute("UPDATE proposals SET status='approved' WHERE id=?", (pid,))
        await db.commit()

    await bot.send_message(CHANNEL_ID, text)
    await callback.message.edit_text("✅ Публикация одобрена и размещена в канале.")

@dp.callback_query(F.data.startswith("reject_"))
async def reject(callback: types.CallbackQuery):
    pid = int(callback.data.split("_")[1])
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("UPDATE proposals SET status='rejected' WHERE id=?", (pid,))
        await db.commit()
    await callback.message.edit_text("❌ Предложение отклонено.")

# === Приём предложений от пользователей ===
@dp.message(lambda m: m.from_user.id not in ADMINS)
async def user_feedback(message: types.Message):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute(
            "INSERT INTO proposals (user_id, username, text) VALUES (?, ?, ?)",
            (message.from_user.id, message.from_user.username, message.text),
        )
        await db.commit()
    await message.answer("✅ Спасибо! Ваше предложение отправлено администраторам.")

# === Запуск ===
async def main():
    await init_db()
    print("✅ Бот запущен. Ждёт видео для постов.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
