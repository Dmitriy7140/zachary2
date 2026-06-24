"""Единая пагинация для всех списков: ◀️ / N/M / ▶️ (с зацикливанием)."""
from aiogram.types import InlineKeyboardButton


def page_slice(items: list, page: int, size: int) -> tuple[list, int, int]:
    """Вернуть (срез, нормализованная_страница, всего_страниц)."""
    pages = max(1, (len(items) + size - 1) // size)
    page %= pages
    return items[page * size:(page + 1) * size], page, pages


def nav_row(page: int, pages: int, prefix: str) -> list[InlineKeyboardButton]:
    """Строка навигации: стрелка влево / N/M / стрелка вправо.

    Стрелки зациклены: с первой страницы ◀️ ведёт на последнюю и наоборот.
    `prefix` — начало callback_data, к которому дописывается номер страницы.
    """
    prev = (page - 1) % pages
    nxt = (page + 1) % pages
    return [
        InlineKeyboardButton(text="◀️", callback_data=f"{prefix}{prev}"),
        InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"),
        InlineKeyboardButton(text="▶️", callback_data=f"{prefix}{nxt}"),
    ]
