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


def main_menu(owner: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Мини-игры", callback_data=f"menu:games:{owner}")],
            [InlineKeyboardButton(text="💼 Работа", callback_data=f"menu:work:{owner}")],
            [InlineKeyboardButton(text="🎒 Инвентарь", callback_data=f"menu:inventory:{owner}")],
            [InlineKeyboardButton(text="🛒 Магазин", callback_data=f"menu:shop:{owner}")],
            # Рынок и Пакости — без owner: только в личке (ensure_private)
            [InlineKeyboardButton(text="🏪 Рынок", callback_data="menu:market")],
            [InlineKeyboardButton(text="🎲 Ставки", callback_data="menu:bets")],
            [InlineKeyboardButton(text="😈 Пакости", callback_data="menu:pranks")],
        ]
    )


def back_menu(owner: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data=f"menu:main:{owner}")]]
    )
