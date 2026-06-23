import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import config
from db import storage
from handlers import companion, registration
from mc.poller import run_poller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


async def main() -> None:
    if not config.bot_token:
        raise SystemExit("BOT_TOKEN не задан — заполни .env")

    await storage.init()

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(registration.router)
    dp.include_router(companion.router)

    # фоновый опрос Minecraft-сервера
    asyncio.create_task(run_poller(bot))

    logging.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
