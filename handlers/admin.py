"""Админские команды."""
from datetime import datetime

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from config import config
from db import storage
from game.daily import process_day
from utils.cleanup import delete_later

router = Router()


@router.message(Command("gimme"))
async def gimme(msg: Message):
    """Чит: начислить себе 100 Z (только админ)."""
    if msg.from_user.id != config.admin_id:
        return
    delete_later(msg.bot, msg.chat.id, msg.message_id)
    profile = await storage.get_profile(msg.from_user.id)
    if not profile:
        sent = await msg.answer("У тебя нет профиля — сначала зарегистрируйся 😉")
    else:
        await storage.add_zbucks(msg.from_user.id, 100)
        sent = await msg.answer(f"💰 +100 Z (чит). Баланс: <b>{profile[3] + 100} Z</b>")
    delete_later(msg.bot, sent.chat.id, sent.message_id)


@router.message(Command("recalc"))
async def recalc(msg: Message, command: CommandObject, bot: Bot):
    """Принудительный пересчёт опыта за день (по умолчанию — сегодня).

    Использование: /recalc            -> за сегодня
                   /recalc 2026-06-23 -> за указанный день
    Внимание: после пересчёта наигранное время за этот день обнуляется.
    """
    if msg.from_user.id != config.admin_id:
        return
    delete_later(msg.bot, msg.chat.id, msg.message_id)
    day = (command.args or "").strip() or datetime.now().date().isoformat()
    await msg.answer(f"⏳ Пересчёт опыта за <b>{day}</b>…")
    try:
        await process_day(bot, day)
    except Exception as e:
        await msg.answer(f"⚠️ Ошибка: <code>{e}</code>")
        return
    sent = await msg.answer("✅ Готово — отчёты разосланы игрокам.")
    delete_later(msg.bot, sent.chat.id, sent.message_id)
