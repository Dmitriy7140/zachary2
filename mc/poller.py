"""Фоновый опрос сервера: ловим заходы/выходы игроков и шлём приветствия."""
import asyncio
import logging

from aiogram import Bot
from aiogram.utils.markdown import hlink

from config import config
from content.greetings import random_greeting, first_time_greeting, random_farewell
from content.ranks import rank
from db import storage
from keyboards import register_kb

log = logging.getLogger(__name__)


async def run_poller(bot: Bot) -> None:
    known_online: set[str] = set()

    # Первый опрос — просто фиксируем, кто уже онлайн, чтобы не
    # приветствовать всех скопом при старте бота.
    initial = await online_players_safe()
    if initial is not None:
        known_online = initial
        log.info("Старт: на сервере %d игрок(ов)", len(known_online))

    try:
        while True:
            await asyncio.sleep(config.poll_interval)
            now = await online_players_safe()
            if now is None:
                continue
            # Копим наигранное время за интервал (только зарегистрированные).
            await storage.add_playtime(now, config.poll_interval)
            # Множества сами разруливают «зашло/вышло сразу несколько».
            for nick in now - known_online:
                try:
                    await handle_join(bot, nick)
                except Exception as e:
                    log.exception("Не удалось обработать заход %s: %s", nick, e)
            for nick in known_online - now:
                try:
                    await handle_leave(bot, nick)
                except Exception as e:
                    log.exception("Не удалось обработать выход %s: %s", nick, e)
            known_online = now
    except asyncio.CancelledError:
        log.info("Поллер остановлен")
        raise


async def online_players_safe() -> set[str] | None:
    from mc.rcon import online_players
    try:
        return set(await online_players())
    except asyncio.TimeoutError:
        log.warning("RCON: таймаут — сервер не ответил")
        return None
    except Exception as e:
        log.warning("RCON опрос не удался: %s", e)
        return None


async def _post(bot: Bot, text: str, kb=None) -> None:
    await bot.send_message(
        chat_id=config.channel_id,
        message_thread_id=config.thread_id or None,
        text=text,
        reply_markup=kb,
    )


async def _nick_display(nick: str) -> str:
    """Звание + ник (ник — ссылка на TG-профиль, если зарегистрирован)."""
    profile = await storage.get_profile_by_nick(nick)
    if profile:
        tg_id, level = profile
        name = hlink(nick, f"tg://user?id={tg_id}")
    else:
        level, name = 0, nick  # незарегистрированный — Новичок без ссылки
    return f"{rank(level)} {name}"


async def handle_join(bot: Bot, nick: str) -> None:
    is_new = await storage.register_seen(nick)
    display = await _nick_display(nick)
    if is_new:
        # Новичок ещё не зарегистрирован — кнопка регистрации по сырому нику.
        await _post(bot, first_time_greeting(display), register_kb(nick))
    else:
        await _post(bot, random_greeting(display))


async def handle_leave(bot: Bot, nick: str) -> None:
    await _post(bot, random_farewell(await _nick_display(nick)))
