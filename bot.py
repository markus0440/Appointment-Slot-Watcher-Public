# bot.py
import asyncio
import contextlib
from typing import Optional

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.exceptions import TelegramRetryAfter

import signal
import os
from dotenv import load_dotenv
load_dotenv()

from web_bot.controller import Controller
from db.db import init_db

from telegram_bot.admin_router import create_admin_router
from telegram_bot.tg_registration import create_user_registration_router, create_admin_registration_router
from telegram_bot.start import make_start_kb

controller = Controller()

TOKEN = os.getenv("API_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
AGREEMENT_PATH = os.getenv("AGREEMENT_PATH", "agreements/pd_agreement.txt")

bot = Bot(TOKEN)
dp = Dispatcher()
router = Router()

async def send_admin_event(event: dict):
    """Уведомления из потока бота админу в чат"""
    if not ADMIN_CHAT_ID:
        return
    t = event.get("type", "event")
    msg = event.get("message", "")
    url = event.get("url", "")
    text = "\n".join(x for x in [f"Событие: {t}", msg, url] if x)
    await bot.send_message(ADMIN_CHAT_ID, text)

async def notify_users(
    chat_ids: list[int],
    city: str,
    flag: bool,
    true_text: str = "Появились заявки, город - ",
    false_text: str = "⚠️ False, город - ",
    per_message_delay_sec: int = 0.1, #пауза между сообщениями
    retry_after_margin_sec: int = 1 #пауза если вышло предупреждение
) -> None:
    """Уведомления пользователям о появлении заявок"""
    text = true_text + city if flag else false_text + city
    
    for chat_id in chat_ids:
        try:
            await bot.send_message(chat_id, text)
            pass

        except TelegramRetryAfter as e:
            # на случай если превышен лимит подождем и попытаемся отправить еще раз
            await asyncio.sleep(retry_after_margin_sec)
            try:
                await bot.send_message(chat_id, text)
            except Exception:
                pass

        except Exception:
            # при другой ошибке пропускаем этого пользователя
            pass

        await asyncio.sleep(per_message_delay_sec)

@router.message(Command("start"))
async def hello(m: Message):
    is_admin = (m.from_user.id == ADMIN_CHAT_ID)
    await m.answer("Привет! Выберите действие:", reply_markup=make_start_kb(is_admin))

# Подключаем роутеры
dp.include_router(router)
dp.include_router(create_user_registration_router(AGREEMENT_PATH))
dp.include_router(create_admin_registration_router(ADMIN_CHAT_ID))
dp.include_router(create_admin_router(controller, ADMIN_CHAT_ID, send_admin_event, notify_users))

async def on_shutdown():
    await controller.stop()

async def main():
    await init_db()
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, loop.stop)
        loop.add_signal_handler(signal.SIGTERM, loop.stop)
    except NotImplementedError:
        pass

    try:
        await dp.start_polling(bot, shutdown=on_shutdown)
    finally:
        await controller.stop()

if __name__ == "__main__":
    asyncio.run(main())
