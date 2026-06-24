"""Фоновый опрос сервера: ловим заходы игроков и шлём приветствия."""
import asyncio
import logging

from aiogram import Bot

from config import config
from content.greetings import random_greeting, first_time_greeting
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
            for nick in now - known_online:
                try:
                    await handle_join(bot, nick)
                except Exception as e:
                    log.exception("Не удалось обработать заход %s: %s", nick, e)
            known_online = now
    except asyncio.CancelledError:
        log.info("Поллер остановлен")
        raise


async def online_players_safe() -> set[str] | None:
    from mc.rcon import online_players
    try:
        return set(await asyncio.wait_for(online_players(), timeout=8))
    except asyncio.TimeoutError:
        log.warning("RCON: таймаут — порт 25575 недоступен (фаервол Яндекса режет вход с бота?)")
        return None
    except Exception as e:
        log.warning("RCON опрос не удался: %s", e)
        return None


async def handle_join(bot: Bot, nick: str) -> None:
    is_new = await storage.register_seen(nick)
    if is_new:
        text, kb = first_time_greeting(nick), register_kb(nick)
    else:
        text, kb = random_greeting(nick), None

    await bot.send_message(
        chat_id=config.channel_id,
        message_thread_id=config.thread_id or None,
        text=text,
        reply_markup=kb,
    )
