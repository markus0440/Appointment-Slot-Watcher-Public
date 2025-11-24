import asyncio
from typing import Awaitable, Callable, Optional
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from telegram_bot.start import make_start_kb

def create_admin_router(controller,
                        admin_chat_id: int,
                        send_admin_event: Optional[Callable[[dict], Awaitable[None]]] = None,
                        notify_users: Optional[Callable[[list[int], str, bool], Awaitable[None]]] = None):
    router = Router()

    def _is_admin(m: Message) -> bool:
        return bool(admin_chat_id) and (m.from_user.id == admin_chat_id)

    @router.message(F.text == "Админ")
    async def admin_menu(m: Message):
        if not _is_admin(m):
            return await m.answer("Недостаточно прав.")
        from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="/start_job"), KeyboardButton(text="/stop_job")],
                [KeyboardButton(text="/run_once"),  KeyboardButton(text="/continue")],
                [KeyboardButton(text="⬅️ Назад")],
            ],
            resize_keyboard=True
        )
        await m.answer("Админ-меню:", reply_markup=kb)

    @router.message(Command("start_job"))
    async def start_job(m: Message):
        if not _is_admin(m):
            return await m.answer("Недостаточно прав.")
        msg = await controller.start(asyncio.get_running_loop(), send_admin_event, notify_users)
        await m.answer(msg)

    @router.message(Command("stop_job"))
    async def stop_job(m: Message):
        if not _is_admin(m):
            return await m.answer("Недостаточно прав.")
        msg = await controller.stop()
        await m.answer(msg)

    @router.message(Command("run_once"))
    async def run_once(m: Message):
        if not _is_admin(m):
            return await m.answer("Недостаточно прав.")
        res = await controller.run_once()
        await m.answer(str(res))

    @router.message(Command("continue"))
    async def cmd_continue(m: Message):
        if not _is_admin(m):
            return await m.answer("Недостаточно прав.")
        ok = await controller.resume()
        await m.answer("Продолжаю." if ok else "Сейчас ничего не на паузе.")

    @router.message(F.text == "⬅️ Назад")
    async def back_to_main(m: Message):
        await m.answer("Ок.", reply_markup=make_start_kb(is_admin=True))

    return router
