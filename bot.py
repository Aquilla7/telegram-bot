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
COMMENTS_CHAT_ID = int(os.getenv("COMMENTS_CHAT_ID", "0"))

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
    rows.append([InlineKeyboardButton(text="💬 Комментировать", callback_data="comment")])
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
            CREATE TABLE IF NOT EXISTS reactions_log (
                user_id INTEGER,
                message_id INTEGER,
                reaction TEXT,
                PRIMARY KEY (user_id, message_id, reaction)
            )
        """)

        cur = await db.execute(
            "SELECT 1 FROM reactions_log WHERE user_id=? AND message_id=? AND reaction=?",
            (user_id, msg_id, field)
        )
        if await cur.fetchone():
            cur = await db.execute(
                f"SELECT {', '.join(REACTIONS.values())} FROM posts WHERE message_id=?",
                (msg_id,)
            )
            row = await cur.fetchone()
            if row:
                reaction_counts = dict(zip(REACTIONS.values(), row))
                await callback.message.edit_reply_markup(reply_markup=post_reactions(reaction_counts))
            return

        cur = await db.execute(
            f"SELECT {', '.join(REACTIONS.values())} FROM posts WHERE message_id=?",
            (msg_id,)
        )
        row = await cur.fetchone()
        if not row:
            return
        reaction_counts = dict(zip(REACTIONS.values(), row))
        reaction_counts[field] += 1

        update_str = ", ".join([f"{k}=?" for k in REACTIONS.values()])
        await db.execute(
            f"UPDATE posts SET {update_str} WHERE message_id=?",
            [*reaction_counts.values(), msg_id]
        )
        await db.execute(
            "INSERT OR IGNORE INTO reactions_log (user_id, message_id, reaction) VALUES (?, ?, ?)",
            (user_id, msg_id, field)
        )
        await db.commit()

    await callback.message.edit_reply_markup(reply_markup=post_reactions(reaction_counts))

# === Комментарии ===
@dp.callback_query(F.data == "comment")
async def comment_prompt(callback: types.CallbackQuery):
    await callback.answer()
    drafts[callback.from_user.id] = {"stage": "waiting_comment"}
    await callback.message.reply("✍ Напиши свой комментарий, и я передам его администраторам.")

@dp.message(lambda m: drafts.get(m.from_user.id, {}).get("stage") == "waiting_comment")
async def comment_receive(message: types.Message):
    await bot.send_message(
        COMMENTS_CHAT_ID,
        f"💬 <b>Комментарий от @{message.from_user.username or message.from_user.full_name}:</b>\n\n{message.text}"
    )
    del drafts[message.from_user.id]
    await message.answer("✅ Комментарий отправлен администраторам, спасибо!")

# === Предложения пользователей ===
@dp.message(F.text == "📬 Предложения пользователей")
async def show_proposals(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    async with aiosqlite.connect("bot.db") as db:
        cur = await db.execute("SELECT id, username, text FROM proposals WHERE status='pending'")
        rows = await cur.fetchall()
    if not rows:
        return await message.answer("📭 Нет новых предложений.")
    for pid, username, text in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{pid}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{pid}")]
        ])
        await message.answer(f"📨 От @{username or 'аноним'}:\n\n{text}", reply_markup=kb)

@dp.callback_query(F.data.startswith("approve_"))
async def approve(callback: types.CallbackQuery):
    pid = int(callback.data.split("_")[1])
    async with aiosqlite.connect("bot.db") as db:
        cur = await db.execute("SELECT text FROM proposals WHERE id=?", (pid,))
        row = await cur.fetchone()
        if not row:
            return await callback.answer("Не найдено.")
        text = row[0]
        await db.execute("UPDATE proposals SET status='approved' WHERE id=?", (pid,))
        await db.commit()
    await bot.send_message(CHANNEL_ID, text, reply_markup=post_reactions({f: 0 for f in REACTIONS.values()}))
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
            (message.from_user.id, message.from_user.username, message.text)
        )
        await db.commit()
    await message.answer("✅ Спасибо! Ваше предложение отправлено администраторам.")

# === Запуск ===
async def main():
    await init_db()
    print("✅ Бот запущен. Напиши ему в Telegram!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
