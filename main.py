import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import config
from db import storage
from game.daily import run_daily_scheduler
from handlers import admin, companion, inventory, minigames, pranks, registration, shop, vovka
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
    dp.include_router(admin.router)
    dp.include_router(registration.router)
    dp.include_router(minigames.router)
    dp.include_router(vovka.router)
    dp.include_router(shop.router)
    dp.include_router(inventory.router)
    dp.include_router(pranks.router)
    dp.include_router(companion.router)

    # фоновый опрос Minecraft-сервера.
    # Ссылку на задачу обязательно держим: иначе сборщик мусора
    # уничтожит её прямо во время работы ("Task was destroyed but it is pending").
    poller_task = asyncio.create_task(run_poller(bot))
    daily_task = asyncio.create_task(run_daily_scheduler(bot))

    logging.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        poller_task.cancel()
        daily_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
