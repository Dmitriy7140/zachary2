"""Отправка объявления в общий тред (с авто-удалением)."""
from aiogram import Bot

from config import config
from utils.cleanup import delete_later


async def announce(bot: Bot, text: str, ttl: int = 60) -> None:
    try:
        sent = await bot.send_message(
            chat_id=config.channel_id, message_thread_id=config.thread_id or None, text=text
        )
        delete_later(bot, sent.chat.id, sent.message_id, ttl)
    except Exception:
        pass
