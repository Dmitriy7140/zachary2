from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def register_kb(nick: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="📝 Зарегистрироваться", callback_data=f"reg:{nick}")
        ]]
    )


def approve_kb(tg_id: int, nick: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"approve:{tg_id}:{nick}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{tg_id}:{nick}"),
        ]]
    )


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Мини-игры", callback_data="menu:games")],
            [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="menu:inventory")],
            [InlineKeyboardButton(text="🛒 Магазин", callback_data="menu:shop")],
            [InlineKeyboardButton(text="😈 Пакости", callback_data="menu:pranks")],
            [InlineKeyboardButton(text="💰 Баланс", callback_data="menu:balance")],
        ]
    )


def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:main")]]
    )
