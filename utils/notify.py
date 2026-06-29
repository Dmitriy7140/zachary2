"""Отправка объявления в общий тред. Эти сообщения НЕ удаляются."""
from aiogram import Bot

from config import config


async def announce(bot: Bot, text: str) -> None:
    try:
        await bot.send_message(
            chat_id=config.channel_id, message_thread_id=config.thread_id or None, text=text
        )
    except Exception:
        pass
