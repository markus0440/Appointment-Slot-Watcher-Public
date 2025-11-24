from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def make_start_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text="📝 Регистрация")]]
    if is_admin:
        rows.append([KeyboardButton(text="🛡️ Регистрация (админ)"), KeyboardButton(text="Админ")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)