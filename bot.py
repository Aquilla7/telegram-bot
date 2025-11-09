import asyncio
import os
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# === Настройки из .env ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMINS = [int(x) for x in os.getenv("ADMINS", "0").split(",") if x.strip() and x != "0"]
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
COMMENTS_CHAT_ID = int(os.getenv("COMMENTS_CHAT_ID", "0"))

from aiogram.client.default import DefaultBotProperties

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)

dp = Dispatcher()

# === Инициализация БД ===
async def init_db():
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                text TEXT,
                likes INTEGER DEFAULT 0,
                loves INTEGER DEFAULT 0,
                fires INTEGER DEFAULT 0
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

# === Клавиатуры ===
def admin_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📝 Создать пост")],
            [types.KeyboardButton(text="📬 Предложения пользователей")]
        ],
        resize_keyboard=True
    )

def post_reactions(likes: int, loves: int, fires: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"👍 {likes}", callback_data="react_like"),
            InlineKeyboardButton(text=f"❤️ {loves}", callback_data="react_love"),
            InlineKeyboardButton(text=f"🔥 {fires}", callback_data="react_fire")
        ],
        [InlineKeyboardButton(text="💬 Комментировать", callback_data="comment")]
    ])

# === /start ===
@dp.message(F.text == "/start")
async def start_cmd(message: types.Message):
    if message.from_user.id in ADMINS:
        await message.answer("👋 Привет, админ!", reply_markup=admin_menu())
    else:
        await message.answer("👋 Привет! Отправь идею поста — администраторы её рассмотрят.")

# === Черновики ===
drafts: dict[int, str | None] = {}
media_drafts: dict[int, dict] = {}

# === Создание поста ===
@dp.message(F.text == "📝 Создать пост")
async def create_post(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    drafts[message.from_user.id] = "waiting_post"
    await message.answer("📄 Отправь текст поста или видео с подписью.")

@dp.message(lambda m: drafts.get(m.from_user.id) == "waiting_post")
async def save_draft(message: types.Message):
    uid = message.from_user.id

    # Видео + подпись (или без)
    if message.video:
        media_drafts[uid] = {"file_id": message.video.file_id, "caption": message.caption or ""}
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Опубликовать", callback_data="publish_video")],
            [InlineKeyboardButton(text="🗑 Отменить", callback_data="cancel")]
        ])
        await message.answer(f"🎥 Видео-пост сохранён.\nПодпись: {media_drafts[uid]['caption'] or '(нет)'}", reply_markup=kb)
        return

    # Текстовый черновик
    if message.text:
        drafts[uid] = message.text
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Опубликовать", callback_data="publish_text")],
            [InlineKeyboardButton(text="🗑 Отменить", callback_data="cancel")]
        ])
        await message.answer(f"📄 Черновик сохранён:\n\n{message.text}", reply_markup=kb)
        return

    await message.answer("⚠️ Пожалуйста, отправь текст или видео с подписью.")

# === Публикация текста ===
@dp.callback_query(F.data == "publish_text")
async def publish_text(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMINS or uid not in drafts or drafts[uid] in (None, "waiting_post"):
        await callback.answer("Ошибка публикации.")
        return

    text = drafts.pop(uid)
    msg = await bot.send_message(chat_id=CHANNEL_ID, text=text, reply_markup=post_reactions(0, 0, 0))

    async with aiosqlite.connect("bot.db") as db:
        await db.execute("INSERT INTO posts (message_id, text) VALUES (?, ?)", (msg.message_id, text))
        await db.commit()

    await callback.message.edit_text("✅ Текстовый пост опубликован в канале.")

# === Публикация видео ===
@dp.callback_query(F.data == "publish_video")
async def publish_video(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMINS or uid not in media_drafts:
        await callback.answer("Ошибка публикации.")
        return

    vd = media_drafts.pop(uid)
    msg = await bot.send_video(chat_id=CHANNEL_ID, video=vd["file_id"], caption=vd["caption"], reply_markup=post_reactions(0, 0, 0))

    async with aiosqlite.connect("bot.db") as db:
        await db.execute("INSERT INTO posts (message_id, text) VALUES (?, ?)", (msg.message_id, vd["caption"]))
        await db.commit()

    await callback.message.edit_text("✅ Видео-пост опубликован в канале.")

# === Отмена черновика ===
@dp.callback_query(F.data == "cancel")
async def cancel(callback: types.CallbackQuery):
    drafts.pop(callback.from_user.id, None)
    media_drafts.pop(callback.from_user.id, None)
    await callback.message.edit_text("🚫 Черновик удалён.")

# === Реакции ===
@dp.callback_query(F.data.startswith("react_"))
async def react(callback: types.CallbackQuery):
    msg_id = callback.message.message_id
    async with aiosqlite.connect("bot.db") as db:
        cur = await db.execute("SELECT likes, loves, fires FROM posts WHERE message_id=?", (msg_id,))
        row = await cur.fetchone()
        if not row:
            await callback.answer("Пост не найден.")
            return
        likes, loves, fires = row
        if callback.data == "react_like":
            likes += 1
        elif callback.data == "react_love":
            loves += 1
        elif callback.data == "react_fire":
            fires += 1
        await db.execute("UPDATE posts SET likes=?, loves=?, fires=? WHERE message_id=?", (likes, loves, fires, msg_id))
        await db.commit()

    await callback.answer("Спасибо за реакцию!")
    await callback.message.edit_reply_markup(reply_markup=post_reactions(likes, loves, fires))

# === Комментарии ===
@dp.callback_query(F.data == "comment")
async def comment_prompt(callback: types.CallbackQuery):
    drafts[callback.from_user.id] = "waiting_comment"
    await callback.answer()
    await callback.message.reply("✍ Напиши свой комментарий, и я передам его администраторам.")

@dp.message(lambda m: drafts.get(m.from_user.id) == "waiting_comment")
async def comment_receive(message: types.Message):
    del drafts[message.from_user.id]
    author = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    await bot.send_message(chat_id=COMMENTS_CHAT_ID, text=f"💬 <b>Комментарий от {author}:</b>\n\n{message.text}")
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
        await message.answer("📭 Нет новых предложений.")
        return
    for pid, username, text in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{pid}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{pid}")]
        ])
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
    msg = await bot.send_message(chat_id=CHANNEL_ID, text=text, reply_markup=post_reactions(0, 0, 0))
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("INSERT INTO posts (message_id, text) VALUES (?, ?)", (msg.message_id, text))
        await db.commit()
    await callback.message.edit_text("✅ Публикация одобрена и размещена в канале.")

@dp.callback_query(F.data.startswith("reject_"))
async def reject(callback: types.CallbackQuery):
    pid = int(callback.data.split("_")[1])
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("UPDATE proposals SET status='rejected' WHERE id=?", (pid,))
        await db.commit()
    await callback.message.edit_text("❌ Предложение отклонено.")

# === Приём предложений от пользователей (личка с ботом) ===
@dp.message(lambda m: m.from_user.id not in ADMINS)
async def user_feedback(message: types.Message):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("INSERT INTO proposals (user_id, username, text) VALUES (?, ?, ?)",
                         (message.from_user.id, message.from_user.username, message.text))
        await db.commit()
    await message.answer("✅ Спасибо! Ваше предложение отправлено администраторам.")

# === Запуск ===
async def main():
    await init_db()
    print("✅ Бот запущен. Напиши ему в Telegram!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
