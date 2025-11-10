import asyncio
import os
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

# === Загружаем токен и настройки из .env ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMINS = [int(x) for x in os.getenv("ADMINS", "0").split(",") if x != "0"]
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

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
                video_path TEXT,
                love INTEGER DEFAULT 0,
                like INTEGER DEFAULT 0,
                clown INTEGER DEFAULT 0,
                angry INTEGER DEFAULT 0,
                think INTEGER DEFAULT 0,
                smile INTEGER DEFAULT 0,
                pray INTEGER DEFAULT 0,
                fire INTEGER DEFAULT 0,
                shock INTEGER DEFAULT 0,
                dislike INTEGER DEFAULT 0
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reactions_log (
                user_id INTEGER,
                message_id INTEGER,
                reaction TEXT,
                PRIMARY KEY (user_id, message_id, reaction)
            )
        """)
        await db.commit()

# === Клавиатуры ===
def admin_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📝 Создать пост")],
            [types.KeyboardButton(text="📬 Предложения пользователей")]
        ],
        resize_keyboard=True
    )

# === Реакции ===
REACTIONS = {
    "❤️": "love",
    "👍": "like",
    "🤡": "clown",
    "😡": "angry",
    "🤔": "think",
    "😅": "smile",
    "🙏": "pray",
    "🔥": "fire",
    "😱": "shock",
    "👎": "dislike"
}

def post_reactions(reaction_counts: dict[str, int]) -> InlineKeyboardMarkup:
    buttons = []
    for emoji, field in REACTIONS.items():
        count = reaction_counts.get(field, 0)
        buttons.append(InlineKeyboardButton(text=f"{emoji} {count}", callback_data=f"react_{field}"))
    half = len(buttons) // 2
    rows = [buttons[:half], buttons[half:]]
    return InlineKeyboardMarkup(inline_keyboard=rows)

# === Команда /start ===
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    if message.from_user.id in ADMINS:
        await message.answer("👋 Привет, админ!", reply_markup=admin_menu())
    else:
        await message.answer("👋 Привет! Отправь идею поста — администраторы её рассмотрят.")

# === Создание поста ===
drafts = {}

@dp.message(F.text == "📝 Создать пост")
async def create_post(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("📄 Введи текст поста:")
    drafts[message.from_user.id] = {"stage": "waiting_post"}

@dp.message(lambda m: drafts.get(m.from_user.id, {}).get("stage") == "waiting_post")
async def save_draft_text(message: types.Message):
    drafts[message.from_user.id] = {"stage": "waiting_video", "text": message.text}
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Опубликовать без видео", callback_data="publish_no_video")]
    ])
    await message.answer("🎬 Если хочешь добавить видео, отправь его сейчас.\n"
                         "Или нажми кнопку, чтобы опубликовать без видео.", reply_markup=kb)

@dp.message(F.video)
async def save_video(message: types.Message):
    if message.from_user.id not in drafts:
        return
    video = message.video
    file = await bot.get_file(video.file_id)
    video_path = f"videos/{video.file_unique_id}.mp4"
    os.makedirs("videos", exist_ok=True)
    await bot.download_file(file.file_path, video_path)
    drafts[message.from_user.id]["video_path"] = video_path
    drafts[message.from_user.id]["stage"] = "ready"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Опубликовать", callback_data="publish")],
        [InlineKeyboardButton(text="🗑 Отменить", callback_data="cancel")]
    ])
    await message.answer("🎥 Видео добавлено. Опубликовать пост?", reply_markup=kb)

@dp.callback_query(F.data.in_(["publish", "publish_no_video"]))
async def publish(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMINS or uid not in drafts:
        return
    text = drafts[uid].get("text", "")
    video_path = drafts[uid].get("video_path")

    if callback.data == "publish_no_video" or not video_path:
        msg = await bot.send_message(CHANNEL_ID, text, reply_markup=post_reactions({f: 0 for f in REACTIONS.values()}))
    else:
        msg = await bot.send_video(CHANNEL_ID, FSInputFile(video_path), caption=text,
                                   reply_markup=post_reactions({f: 0 for f in REACTIONS.values()}))

    async with aiosqlite.connect("bot.db") as db:
        await db.execute("INSERT INTO posts (message_id, text, video_path) VALUES (?, ?, ?)",
                         (msg.message_id, text, video_path))
        await db.commit()
    del drafts[uid]
    await callback.message.edit_text("✅ Пост опубликован в канале.")

@dp.callback_query(F.data == "cancel")
async def cancel(callback: types.CallbackQuery):
    drafts.pop(callback.from_user.id, None)
    await callback.message.edit_text("🚫 Черновик удалён.")

# === Обработка реакций с антиспамом ===
@dp.callback_query(F.data.startswith("react_"))
async def react(callback: types.CallbackQuery):
    field = callback.data.replace("react_", "")
    user_id = callback.from_user.id
    msg_id = callback.message.message_id

    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT
