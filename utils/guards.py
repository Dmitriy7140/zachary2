"""Защита кликов по меню."""
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery


async def ensure_private(cb: CallbackQuery) -> bool:
    """True, если клик из личного чата (для пакостей)."""
    if cb.message.chat.type != ChatType.PRIVATE:
        await cb.answer("Пакости работают только в личке бота 😉", show_alert=True)
        return False
    return True


def with_owner(data: str, owner: int) -> str:
    """Дописать id владельца меню в конец callback_data."""
    return f"{data}:{owner}"


async def ensure_owner(cb: CallbackQuery) -> bool:
    """True, если жмёт тот, кому принадлежит меню (id владельца — в конце callback_data).

    Работает в любом чате (личка/группа): чужой игрок нажать не сможет.
    """
    try:
        owner = int(cb.data.rsplit(":", 1)[-1])
    except (ValueError, IndexError, TypeError):
        return True  # нет owner в данных — пропускаем
    if owner != cb.from_user.id:
        await cb.answer("Это не твоё меню — набери /start у себя 😉", show_alert=True)
        return False
    return True
