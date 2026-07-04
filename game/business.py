"""Бизнесы: константы, планировщик продукции/содержания/отмыва.

Первый бизнес — «Комар-фарм Логистикс» (малый, tier='small'):
  • продукция: 1–2 яйца в час, падают в инвентарь, личка владельцу (НЕ тред);
  • содержание: UPKEEP Z в день; нет денег — бизнес на паузе до оплаты;
  • отмыв: закладка грязных возвращается чистой через LAUNDER_HOURS,
    одновременно в стирке не больше LAUNDER_CAP (на 1 уровне).
"""
import asyncio
import html
import logging
import random
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.utils.markdown import hlink

from content.business import (launder_done, produce, se_tax_fail, se_tax_paid, upkeep_fail,
                              upkeep_paid, upkeep_resume)
from db import storage
from game.items import ITEMS
from game.taxman import grant
from utils.notify import announce

log = logging.getLogger(__name__)

BIZ_MOSQUITO = "mosquito_farm"
TIER_SMALL = "small"                # малый бизнес (потом medium/large)
MOSQUITO_PRICE = 20_000
MOSQUITO_UPKEEP = 200               # Z/день на 1 уровне; +100 за каждый уровень
MOSQUITO_EGGS = (2, 3)              # яиц в час: при максимуме и продаже по 40 Z
                                    # окупаемость ~неделя (см. расчёт в PR)
MOSQUITO_CORN = (1, 2)              # кукурузы в час со 2 уровня: при максимуме
                                    # и продаже по 50 Z апгрейд окупается ~за неделю
MOSQUITO_POTATO = (1, 2)            # картофеля в час с 3 уровня: при максимуме
                                    # и продаже по 60 Z апгрейд окупается ~за неделю
UPGRADE2_PRICE = 15_000             # улучшение до 2 уровня (кукуруза)
UPGRADE3_PRICE = 20_000             # улучшение до 3 уровня (картофель-батат)


def upkeep_for(level: int) -> int:
    """Содержание: 200 на 1 уровне, +100 за зарплаты на каждом следующем."""
    return MOSQUITO_UPKEEP + 100 * (level - 1)


def launder_cap_for(level: int) -> int:
    """Потолок стирки: 4000 на 1 уровне, +1000 простора за уровень."""
    return LAUNDER_CAP + 1000 * (level - 1)
LAUNDER_CAP = 4000                  # одновременно в стирке на 1 уровне
LAUNDER_HOURS = 24

SELF_EMPLOY_COST = 1000             # разовый платёж за регистрацию
SELF_EMPLOY_TAX = 200               # фиксированный налог самозанятого, Z/день
SE_TAX_KEY = "se_tax"               # ключ в cooldowns: когда списывать в следующий раз
DEFAULT_NAME = "Комар-фарм Логистикс"
NAME_MAXLEN = 40


# титул конторы растёт вместе с уровнем
_LEVEL_PREFIX = {
    1: "Сброд комаров",
    2: "Комариная логистическая компания",
    3: "Комариный логистический холдинг",
}


def biz_display(custom_name: str | None, level: int = 1) -> str:
    """Имя бизнеса для объявлений: «Префикс уровня «Название»»."""
    name = html.escape(custom_name) if custom_name else DEFAULT_NAME
    prefix = _LEVEL_PREFIX[min(max(level, 1), 3)]
    return f"{prefix} «{name}»"


async def owner_mention(tg_id: int) -> str:
    profile = await storage.get_profile(tg_id)
    return hlink(profile[2] if profile else "Игрок", f"tg://user?id={tg_id}")


async def run_business_scheduler(bot: Bot) -> None:
    """Фоновый цикл: продукция раз в час, содержание раз в день, выдача отмытого."""
    try:
        while True:
            try:
                await _tick(bot)
            except Exception as e:
                log.exception("Бизнес: ошибка планировщика: %s", e)
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        log.info("Планировщик бизнесов остановлен")
        raise


async def _tick(bot: Bot) -> None:
    now = datetime.now()
    now_iso = now.isoformat()

    # 1. продукция (только личка владельцу)
    for tg_id, biz, level, _name in await storage.due_production(now_iso):
        await storage.set_produce_at(tg_id, biz, (now + timedelta(hours=1)).isoformat())
        n = random.randint(*MOSQUITO_EGGS)
        await storage.add_item(tg_id, "egg", n, ITEMS["egg"].max_qty)
        corn = potato = 0
        if level >= 2:  # со 2 уровня комары возят «кукурузу»
            corn = random.randint(*MOSQUITO_CORN)
            await storage.add_item(tg_id, "corn", corn, ITEMS["corn"].max_qty)
        if level >= 3:  # с 3 уровня — «картофель» (батат, но кого это волнует)
            potato = random.randint(*MOSQUITO_POTATO)
            await storage.add_item(tg_id, "potato", potato, ITEMS["potato"].max_qty)
        try:
            await bot.send_message(tg_id, produce(n, corn, potato))
        except Exception:
            pass

    # 2. содержание (ежедневно); не хватило — пауза до следующего успешного списания
    for tg_id, biz, level, _name, paused in await storage.due_upkeep(now_iso):
        await storage.set_upkeep_at(tg_id, biz, (now + timedelta(days=1)).isoformat())
        if await storage.spend_zbucks(tg_id, upkeep_for(level)):
            try:
                await bot.send_message(tg_id, upkeep_paid(upkeep_for(level)))
            except Exception:
                pass
            if paused:
                await storage.set_business_paused(tg_id, biz, False)
                # пауза снята — продукция снова через час
                await storage.set_produce_at(tg_id, biz, (now + timedelta(hours=1)).isoformat())
                try:
                    await bot.send_message(tg_id, upkeep_resume())
                except Exception:
                    pass
        else:
            if not paused:
                await storage.set_business_paused(tg_id, biz, True)
            try:
                await bot.send_message(tg_id, upkeep_fail(upkeep_for(level)))
            except Exception:
                pass

    # 3. налог самозанятого: 200 Z/день с каждого зарегистрированного
    for tg_id in await storage.self_employed_ids():
        due = await storage.get_cooldown(tg_id, SE_TAX_KEY)
        if due is None:
            # первый раз видим (регистрация до появления налога) — стартуем отсчёт
            await storage.set_cooldown_until(
                tg_id, SE_TAX_KEY, (now + timedelta(days=1)).isoformat())
            continue
        if datetime.fromisoformat(due) > now:
            continue
        await storage.set_cooldown_until(
            tg_id, SE_TAX_KEY, (now + timedelta(days=1)).isoformat())
        if await storage.spend_zbucks(tg_id, SELF_EMPLOY_TAX):
            msg = se_tax_paid(SELF_EMPLOY_TAX)
        else:
            msg = se_tax_fail(SELF_EMPLOY_TAX)
        try:
            await bot.send_message(tg_id, msg)
        except Exception:
            pass

    # 4. отмыв: возвращаем чистыми (личка + тред)
    for lid, tg_id, amount in await storage.due_laundering(now_iso):
        await storage.remove_laundering(lid)
        await grant(bot, tg_id, amount)  # чистые
        biz_row = await storage.get_business(tg_id, BIZ_MOSQUITO)
        biz_name = biz_display(biz_row[2] if biz_row else None,
                               biz_row[1] if biz_row else 1)
        try:
            await bot.send_message(tg_id, f"✨ Отмыв завершён: +{amount} Z чистыми.")
        except Exception:
            pass
        await announce(bot, launder_done(await owner_mention(tg_id), biz_name, amount))
