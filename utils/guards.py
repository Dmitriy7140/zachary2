"""Защита: действия с балансом — только в личке самого игрока."""
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery


async def ensure_private(cb: CallbackQuery) -> bool:
    """True, если клик пришёл из личного чата (значит, жмёт сам владелец).

    В личке inline-кнопки доступны только владельцу чата, поэтому чужой
    нажать не может. Плюс мы всегда работаем с cb.from_user.id — так что
    потратить чужой баланс нельзя.
    """
    if cb.message.chat.type != ChatType.PRIVATE:
        await cb.answer("Это меню работает только в личке бота 😉", show_alert=True)
        return False
    return True
