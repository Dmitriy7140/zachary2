import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import config
from db import storage
from game.bets import run_bets_scheduler
from game.business import run_business_scheduler
from game.daily import run_daily_scheduler
from game.debts import run_debts_scheduler
from game.fishing import run_fishing_scheduler
from game.market import run_market_scheduler
from game.richest import run_richest_watcher
from game.taxman import run_gustav_scheduler
from handlers import (admin, bets, business, cashier, companion, courier, farca, finance,
                      fishing, inventory, loan, market, minigames, pranks, registration,
                      roulette, scammer, shady, shop, stats, vovka, work)
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
    dp.include_router(stats.router)
    dp.include_router(registration.router)
    dp.include_router(minigames.router)
    dp.include_router(vovka.router)
    dp.include_router(roulette.router)
    dp.include_router(fishing.router)
    dp.include_router(shop.router)
    dp.include_router(inventory.router)
    dp.include_router(work.router)
    dp.include_router(cashier.router)
    dp.include_router(courier.router)
    dp.include_router(farca.router)
    dp.include_router(scammer.router)
    dp.include_router(market.router)
    dp.include_router(bets.router)
    dp.include_router(loan.router)
    dp.include_router(finance.router)
    dp.include_router(shady.router)
    dp.include_router(business.router)
    dp.include_router(pranks.router)
    dp.include_router(companion.router)

    # фоновый опрос Minecraft-сервера.
    # Ссылку на задачу обязательно держим: иначе сборщик мусора
    # уничтожит её прямо во время работы ("Task was destroyed but it is pending").
    poller_task = asyncio.create_task(run_poller(bot))
    daily_task = asyncio.create_task(run_daily_scheduler(bot))
    market_task = asyncio.create_task(run_market_scheduler(bot))
    bets_task = asyncio.create_task(run_bets_scheduler(bot))
    debts_task = asyncio.create_task(run_debts_scheduler(bot))
    richest_task = asyncio.create_task(run_richest_watcher(bot))
    fishing_task = asyncio.create_task(run_fishing_scheduler(bot))
    gustav_task = asyncio.create_task(run_gustav_scheduler(bot))
    business_task = asyncio.create_task(run_business_scheduler(bot))

    logging.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        poller_task.cancel()
        daily_task.cancel()
        market_task.cancel()
        bets_task.cancel()
        debts_task.cancel()
        richest_task.cancel()
        fishing_task.cancel()
        gustav_task.cancel()
        business_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
