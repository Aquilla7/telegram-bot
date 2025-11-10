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
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                text TEXT,
                video_path TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                text TEXT,
                status TEXT DEFAULT 'pending'
            )
            """
        )
        await db.commit()

# === Клавиатуры ===
def admin_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text]()
