import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import config
from db import storage
from game.bets import run_bets_scheduler
from game.business import run_business_scheduler
from game.cube import bootstrap_cube, run_cube_scheduler
from game.daily import run_daily_scheduler
from game.debts import run_debts_scheduler
from game.fishing import run_fishing_scheduler
from game.lottery import ensure_current_round, run_lottery_scheduler
from game.market import run_market_scheduler
from game.richest import run_richest_watcher
from game.taxman import run_gustav_scheduler
from handlers import (admin, bets, business, cashier, chef, companion, courier, cube,
                      farca, finance, fishing, inventory, loan, lottery, market, minigames,
                      pranks, registration, roulette, scammer, shady, shop, stats,
                      vovka, vpn, work)
from mc.poller import run_poller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


async def main() -> None:
    if not config.bot_token:
        raise SystemExit("BOT_TOKEN не задан — заполни .env")

    await storage.init()

    try:
        # Polling не должен стартовать без долговечного текущего тиража.
        await ensure_current_round()
        # Куб тоже должен существовать до первого пользовательского callback.
        await bootstrap_cube()

        bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dp = Dispatcher()
        dp.include_router(admin.router)
        dp.include_router(stats.router)
        dp.include_router(registration.router)
        dp.include_router(minigames.router)
        dp.include_router(cube.router)
        dp.include_router(lottery.router)
        dp.include_router(vovka.router)
        dp.include_router(roulette.router)
        dp.include_router(fishing.router)
        dp.include_router(shop.router)
        dp.include_router(inventory.router)
        dp.include_router(work.router)
        dp.include_router(cashier.router)
        dp.include_router(courier.router)
        dp.include_router(chef.router)
        dp.include_router(vpn.router)
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

        # Сильные ссылки не дают сборщику мусора уничтожить фоновые
        # задачи, а единый список позволяет корректно дождаться cancel.
        tasks = [
            asyncio.create_task(run_poller(bot)),
            asyncio.create_task(run_daily_scheduler(bot)),
            asyncio.create_task(run_market_scheduler(bot)),
            asyncio.create_task(run_bets_scheduler(bot)),
            asyncio.create_task(run_debts_scheduler(bot)),
            asyncio.create_task(run_richest_watcher(bot)),
            asyncio.create_task(run_fishing_scheduler(bot)),
            asyncio.create_task(run_gustav_scheduler(bot)),
            asyncio.create_task(run_business_scheduler(bot)),
            asyncio.create_task(run_lottery_scheduler(bot)),
            asyncio.create_task(run_cube_scheduler(bot)),
        ]

        logging.info("Бот запущен")
        try:
            # Сессию закроем сами после cancel update-handlers: aiogram
            # не ждёт их автоматически при остановке polling.
            await dp.start_polling(bot, close_bot_session=False)
        finally:
            update_tasks = list(dp._handle_update_tasks)
            for task in [*tasks, *update_tasks]:
                task.cancel()
            await asyncio.gather(*tasks, *update_tasks, return_exceptions=True)
            await bot.session.close()
    finally:
        await storage.close()


if __name__ == "__main__":
    asyncio.run(main())
