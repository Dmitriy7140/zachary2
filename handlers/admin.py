"""Админские команды."""
from datetime import datetime

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from config import config
from game.daily import process_day

router = Router()


@router.message(Command("recalc"))
async def recalc(msg: Message, command: CommandObject, bot: Bot):
    """Принудительный пересчёт опыта за день (по умолчанию — сегодня).

    Использование: /recalc            -> за сегодня
                   /recalc 2026-06-23 -> за указанный день
    Внимание: после пересчёта наигранное время за этот день обнуляется.
    """
    if msg.from_user.id != config.admin_id:
        return
    day = (command.args or "").strip() or datetime.now().date().isoformat()
    await msg.answer(f"⏳ Пересчёт опыта за <b>{day}</b>…")
    try:
        await process_day(bot, day)
    except Exception as e:
        await msg.answer(f"⚠️ Ошибка: <code>{e}</code>")
        return
    await msg.answer("✅ Готово — отчёты разосланы игрокам.")
