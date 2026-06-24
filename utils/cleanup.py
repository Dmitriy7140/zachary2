"""Авто-удаление сообщений бота/команд через заданное время."""
import asyncio

from aiogram import Bot

_tasks: set = set()  # держим ссылки, чтобы GC не убил фоновые задачи


def delete_later(bot: Bot, chat_id: int, message_id: int, delay: int = 60) -> None:
    async def _job():
        try:
            await asyncio.sleep(delay)
            await bot.delete_message(chat_id, message_id)
        except Exception:
            pass  # сообщение уже удалено / нет прав / устарело

    task = asyncio.create_task(_job())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
