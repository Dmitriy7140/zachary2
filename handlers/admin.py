"""Админские команды."""
from datetime import datetime

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from config import config
from db import storage
from game.daily import process_day
from game.taxman import grant

router = Router()


@router.message(Command("gimme"))
async def gimme(msg: Message):
    """Чит: начислить себе 100 Z (только админ)."""
    if msg.from_user.id != config.admin_id:
        return
    profile = await storage.get_profile(msg.from_user.id)
    if not profile:
        return await msg.answer("У тебя нет профиля — сначала зарегистрируйся 😉")
    await grant(msg.bot, msg.from_user.id, 100)
    await msg.answer(f"💰 +100 Z (чит). Баланс: <b>{profile[3] + 100} Z</b>")


@router.message(Command("resetcd"))
async def reset_cd(msg: Message):
    """Сбросить все кулдауны по играм (у всех)."""
    if msg.from_user.id != config.admin_id:
        return
    n = await storage.reset_all_cooldowns()
    await msg.answer(f"♻️ Сброшены все кулдауны по играм (записей: {n}).")


@router.message(Command("clearitems"))
async def clear_items(msg: Message):
    """Удалить все предметы у себя."""
    if msg.from_user.id != config.admin_id:
        return
    n = await storage.clear_inventory(msg.from_user.id)
    await msg.answer(f"🗑 Удалены все твои предметы (записей: {n}).")


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
        await process_day(bot, day, allowance=False)  # пособие не дублируем при ручном пересчёте
    except Exception as e:
        await msg.answer(f"⚠️ Ошибка: <code>{e}</code>")
        return
    await msg.answer("✅ Готово — отчёты разосланы игрокам.")
