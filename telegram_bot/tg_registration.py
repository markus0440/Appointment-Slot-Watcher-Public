import os
from contextlib import suppress
from aiogram import Router, F, types
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton,
                           InlineKeyboardMarkup, InlineKeyboardButton,
                           ReplyKeyboardRemove)
from telegram_bot.start import make_start_kb
from db.data_access import UserActions

# регистрация для пользователя
def create_user_registration_router(agreement_path: str) -> Router:
    router = Router()

    def _load_agreement() -> str:
        try:
            with open(agreement_path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            return text
        except Exception:
            return ("Соглашение об обработке персональных данных:\n\n"
                    "Нажимая «Согласен», вы подтверждаете согласие на обработку ваших персональных данных "
                    "в объёме, необходимом для работы бота.")

    @router.message(F.text.in_(["📝 Регистрация", "Регистрация", "/register"]))
    async def user_registration_start(m: types.Message):
        if not m.from_user.username:
            return await m.answer(
                "У вас не задан @username в Telegram. Задайте ник в настройках и повторите попытку."
            )

        agreement_text = _load_agreement()
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Согласен", callback_data="ureg:agree"),
            InlineKeyboardButton(text="✖️ Отмена", callback_data="ureg:cancel"),
        ]])
        await m.answer(agreement_text, reply_markup=kb)

    @router.callback_query(F.data == "ureg:cancel")
    async def user_registration_cancel(q: types.CallbackQuery):
        with suppress(Exception):
            await q.message.edit_reply_markup(reply_markup=None)
        await q.message.answer("Ок, регистрацию отменили.", reply_markup=make_start_kb())
        await q.answer()

    @router.callback_query(F.data == "ureg:agree")
    async def user_registration_confirm(q: types.CallbackQuery):
        if not q.from_user.username:
            with suppress(Exception):
                await q.message.edit_reply_markup(reply_markup=None)
            await q.message.answer(
                "У вас не задан @username в Telegram. Задайте ник в настройках и повторите попытку."
            )
            return await q.answer()

        try:
            user = await UserActions().register_basic_user(
                telegram_username=q.from_user.username,
                chat_id=q.from_user.id
            )
        except ValueError as e:
            with suppress(Exception):
                await q.message.edit_reply_markup(reply_markup=None)
            await q.message.answer(f"❌ {e}\nПопробуйте ещё раз с команды «Регистрация».")
            return await q.answer()

        with suppress(Exception):
            await q.message.edit_reply_markup(reply_markup=None)

        await q.message.edit_text(
            "✅ Регистрация завершена!\n"
            f"Telegram: <b>@{user.telegram_username}</b>\n",
            parse_mode="HTML"
        )
        await q.message.answer("Готово. Когда появятся окна для записи - вам придет уведомление.", reply_markup=make_start_kb())
        await q.answer()

    return router

# регистрация для админа
class AdminReg(StatesGroup):
    login = State()
    password = State()
    apply_status = State()
    city = State()
    confirm = State()

def create_admin_registration_router(admin_chat_id: int) -> Router:
    router = Router()

    def _is_admin(msg: types.Message | types.CallbackQuery) -> bool:
        user = msg.from_user if isinstance(msg, types.CallbackQuery) else msg.from_user
        return bool(admin_chat_id) and (user.id == admin_chat_id)

    @router.message(F.text.in_(["🛡️ Регистрация (админ)", "/admin_register"]))
    async def start_registration(m: types.Message, state: FSMContext):
        if not _is_admin(m):
            return await m.answer("Эта команда доступна только администратору.")
        if not m.from_user.username:
            await m.answer("У вас не задан @username в Telegram. Задайте ник в настройках и повторите попытку.")
            return
        await state.clear()
        await state.update_data(tg_username=m.from_user.username)
        await m.answer("🔑 Регистрация с правами администратора")
        await state.set_state(AdminReg.login)
        await m.answer("Введите желаемый логин:", reply_markup=ReplyKeyboardRemove())

    @router.message(AdminReg.login)
    async def take_login(m: types.Message, state: FSMContext):
        if not _is_admin(m):
            return await m.answer("Эта команда доступна только администратору.")
        login = (m.text or "").strip()
        if len(login) < 3:
            await m.answer("Логин должен быть не короче 3 символов. Попробуйте ещё раз:")
            return
        await state.update_data(login=login)
        await state.set_state(AdminReg.password)
        await m.answer("Введите пароль:", parse_mode="Markdown")

    @router.message(AdminReg.password)
    async def take_password(m: types.Message, state: FSMContext):
        if not _is_admin(m):
            return await m.answer("Эта команда доступна только администратору.")
        pwd = (m.text or "").strip()
        if not pwd:
            await m.answer("Пароль не может быть пустым. Введите ещё раз:")
            return
        await state.update_data(password_encrypted=pwd)

        data = await state.get_data()
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="admreg:confirm"),
            InlineKeyboardButton(text="↩️ Заполнить заново", callback_data="admreg:restart"),
        ]])
        await state.set_state(AdminReg.confirm)
        await m.answer(
            "Проверьте данные:\n"
            f"• Логин: <b>{data['login']}</b>\n"
            f"• Telegram: <b>@{data['tg_username']}</b>",
            parse_mode="HTML",
            reply_markup=kb
        )

    @router.callback_query(F.data == "admreg:restart")
    async def restart(q: types.CallbackQuery, state: FSMContext):
        if not _is_admin(q):
            return await q.answer("Недоступно.", show_alert=True)
        await state.clear()
        if q.from_user.username:
            await state.update_data(tg_username=q.from_user.username)
        with suppress(Exception):
            await q.message.edit_reply_markup(reply_markup=None)
        await state.set_state(AdminReg.login)
        await q.message.answer("Ок, заполняем заново. Введите желаемый логин:", reply_markup=ReplyKeyboardRemove())
        await q.answer()

    @router.callback_query(F.data == "admreg:confirm")
    async def confirm(q: types.CallbackQuery, state: FSMContext):
        if not _is_admin(q):
            return await q.answer("Недоступно.", show_alert=True)
        data = await state.get_data()
        try:
            user = await UserActions().register_user(
                login=data["login"],
                password_encrypted=data["password_encrypted"],
                telegram_username=data["tg_username"],
            )
        except ValueError as e:
            with suppress(Exception):
                await q.message.edit_reply_markup(reply_markup=None)
            await state.clear()
            if q.from_user.username:
                await state.update_data(tg_username=q.from_user.username)
            await state.set_state(AdminReg.login)
            await q.message.answer(f"❌ {e}\n\nПопробуем ещё раз. Введите желаемый логин:", reply_markup=ReplyKeyboardRemove())
            await q.answer()
            return

        await state.clear()
        with suppress(Exception):
            await q.message.edit_reply_markup(reply_markup=None)

        text = (
            "✅ Регистрация завершена!\n"
            f"Ваш id: <b>{user.id}</b>\n"
            f"Логин: <b>{user.login}</b>\n"
            f"Telegram: <b>@{user.telegram_username}</b>"
        )
        await q.message.edit_text(text, parse_mode="HTML")
        await q.message.answer("Готово. Что дальше?", reply_markup=make_start_kb(is_admin=True))
        await q.answer()

    return router
