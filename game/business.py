"""Правила легальных бизнесов и их минутный планировщик."""
import asyncio
import html
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.utils.markdown import hlink

from content import slugs as slug_text
from content.business import (launder_done, produce, se_tax_fail, se_tax_paid, upkeep_fail,
                              upkeep_paid, upkeep_resume)
from db import storage
from game.items import ITEMS
from game.taxman import maybe_gustav
from utils.notify import announce

log = logging.getLogger(__name__)

BIZ_MOSQUITO = "mosquito_farm"
BIZ_SLUGS = "slug_bistro"
BIZ_SLUG_BISTRO = BIZ_SLUGS
BUSINESS_KEYS = (BIZ_MOSQUITO, BIZ_SLUGS)
TIER_SMALL = "small"

# Комариная логистическая компания.
MOSQUITO_PRICE = 20_000
MOSQUITO_UPKEEP = 200
MOSQUITO_EGGS = (2, 3)
MOSQUITO_CORN = (1, 2)
MOSQUITO_POTATO = (1, 2)
UPGRADE2_PRICE = 15_000
UPGRADE3_PRICE = 20_000
DEFAULT_NAME = "Комар-фарм Логистикс"

# Пирожки слизней.
SLUG_PRICE = 20_000
SLUG_UPGRADE2_PRICE = 25_000
SLUG_UPGRADE3_PRICE = 30_000
SLUG_DEFAULT_NAME = "Пироги слизней"
SLUG_LORE = slug_text.SLUG_LORE

LAUNDER_CAP = 4_000
LAUNDER_HOURS = 24
SELF_EMPLOY_COST = 1_000
SELF_EMPLOY_TAX = 200
SE_TAX_KEY = "se_tax"
NAME_MAXLEN = 40


@dataclass(frozen=True)
class SlugRecipe:
    item: str
    ingredient: str
    ingredient_qty: int
    minutes: int
    unlock_level: int


SLUG_RECIPES = {
    "slime_pie": SlugRecipe("slime_pie", "egg", 5, 15, 1),
    "slime_pita": SlugRecipe("slime_pita", "corn", 4, 20, 2),
    "slime_dranik": SlugRecipe("slime_dranik", "potato", 3, 25, 3),
}

_MOSQUITO_LEVEL_PREFIX = {
    1: "Сброд комаров",
    2: "Комариная логистическая компания",
    3: "Комариный логистический холдинг",
}
_SLUG_LEVEL_PREFIX = {
    1: "Палатка с чебуреками и слизнями",
    2: "Слизневое бистро на углу",
    3: "ПАО Слизни и точка",
}


def business_card_name(biz: str) -> str:
    return {BIZ_MOSQUITO: "🦟 Комар-фарм Логистикс", BIZ_SLUGS: "🐌 Пироги слизней"}.get(
        biz, "Неизвестная контора")


def business_purchase_price(biz: str) -> int:
    return {BIZ_MOSQUITO: MOSQUITO_PRICE, BIZ_SLUGS: SLUG_PRICE}[biz]


def upkeep_for(level: int, biz: str = BIZ_MOSQUITO) -> int:
    """Ежедневная зарплата/содержание на конкретном уровне."""
    level = min(max(level, 1), 3)
    if biz == BIZ_SLUGS:
        return 300 + 100 * (level - 1)
    return MOSQUITO_UPKEEP + 100 * (level - 1)


def launder_cap_for(level: int) -> int:
    """У каждого бизнеса свой, но одинаковый по уровням, потолок стирки."""
    return LAUNDER_CAP + 1_000 * (min(max(level, 1), 3) - 1)


def upgrade_price(biz: str, level: int) -> int | None:
    if level >= 3:
        return None
    if biz == BIZ_SLUGS:
        return SLUG_UPGRADE2_PRICE if level == 1 else SLUG_UPGRADE3_PRICE
    return UPGRADE2_PRICE if level == 1 else UPGRADE3_PRICE


def biz_display(custom_name: str | None, level: int = 1, biz: str = BIZ_MOSQUITO) -> str:
    """Публичное имя: уровень остаётся видимым после пользовательского ребрендинга."""
    level = min(max(level, 1), 3)
    if biz == BIZ_SLUGS:
        prefix = _SLUG_LEVEL_PREFIX[level]
        name = html.escape(custom_name) if custom_name else SLUG_DEFAULT_NAME
    else:
        prefix = _MOSQUITO_LEVEL_PREFIX[level]
        name = html.escape(custom_name) if custom_name else DEFAULT_NAME
    return f"{prefix} «{name}»"


def get_slug_recipe(item: str) -> SlugRecipe | None:
    return SLUG_RECIPES.get(item)


def available_slug_recipes(level: int) -> list[SlugRecipe]:
    return [recipe for recipe in SLUG_RECIPES.values() if recipe.unlock_level <= level]


def slug_recipe_limit(active_jobs: int, ingredient_qty: int, product_qty: int,
                      recipe: SlugRecipe) -> int:
    """Сколько единиц можно поставить в одну кнопку без очереди и переполнения."""
    return max(0, min(5 - active_jobs, ingredient_qty // recipe.ingredient_qty,
                      ITEMS[recipe.item].max_qty - product_qty))


async def owner_mention(tg_id: int) -> str:
    profile = await storage.get_profile(tg_id)
    return hlink(profile[2] if profile else "Игрок", f"tg://user?id={tg_id}")


async def run_business_scheduler(bot: Bot) -> None:
    """Минутный цикл: комариная продукция, зарплаты, отмыв и готовка слизней."""
    try:
        while True:
            try:
                await _tick(bot)
            except Exception as exc:
                log.exception("Бизнес: ошибка планировщика: %s", exc)
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        log.info("Планировщик бизнесов остановлен")
        raise


async def _tick(bot: Bot) -> None:
    now = datetime.now()
    now_iso = now.isoformat()
    await _process_mosquito_production(bot, now, now_iso)
    await _process_upkeep(bot, now, now_iso)
    await _process_self_employed_tax(bot, now)
    await _process_laundering(bot, now_iso)
    await _process_slug_cooking(bot, now_iso)


async def _process_mosquito_production(bot: Bot, now: datetime, now_iso: str) -> None:
    for tg_id, biz, level, _name in await storage.due_production(now_iso):
        # produce_at принадлежит старой автоматической логистике, не бистро.
        if biz != BIZ_MOSQUITO:
            continue
        await storage.set_produce_at(tg_id, biz, (now + timedelta(hours=1)).isoformat())
        eggs = random.randint(*MOSQUITO_EGGS)
        await storage.add_item(tg_id, "egg", eggs, ITEMS["egg"].max_qty)
        corn = potato = 0
        if level >= 2:
            corn = random.randint(*MOSQUITO_CORN)
            await storage.add_item(tg_id, "corn", corn, ITEMS["corn"].max_qty)
        if level >= 3:
            potato = random.randint(*MOSQUITO_POTATO)
            await storage.add_item(tg_id, "potato", potato, ITEMS["potato"].max_qty)
        try:
            await bot.send_message(tg_id, produce(eggs, corn, potato))
        except Exception:
            pass


async def _process_upkeep(bot: Bot, now: datetime, now_iso: str) -> None:
    for tg_id, biz, level, _name, _paused in await storage.due_upkeep(now_iso):
        if biz not in BUSINESS_KEYS:
            continue
        amount = upkeep_for(level, biz)
        settlement = await storage.settle_business_upkeep_atomic(
            tg_id,
            biz,
            amount,
            now_iso,
            (now + timedelta(days=1)).isoformat(),
            # У слизней нет почасовой produce_at; комары после снятия паузы
            # начинают новый час работы, как и раньше.
            (now + timedelta(hours=1)).isoformat() if biz == BIZ_MOSQUITO else None,
        )
        if settlement.status in {"not_due", "not_owned"}:
            continue
        if settlement.status == "paid":
            try:
                await bot.send_message(
                    tg_id,
                    upkeep_paid(amount) if biz == BIZ_MOSQUITO else slug_text.upkeep_paid(amount),
                )
            except Exception:
                pass
            if settlement.was_paused:
                try:
                    await bot.send_message(
                        tg_id,
                        upkeep_resume() if biz == BIZ_MOSQUITO else slug_text.upkeep_resume(),
                    )
                except Exception:
                    pass
        else:  # unpaid: пауза и следующая дата уже зафиксированы одним commit.
            try:
                await bot.send_message(
                    tg_id,
                    upkeep_fail(amount) if biz == BIZ_MOSQUITO else slug_text.upkeep_fail(amount),
                )
            except Exception:
                pass


async def _process_self_employed_tax(bot: Bot, now: datetime) -> None:
    for tg_id in await storage.self_employed_ids():
        due = await storage.get_cooldown(tg_id, SE_TAX_KEY)
        if due is None:
            await storage.set_cooldown_until(tg_id, SE_TAX_KEY, (now + timedelta(days=1)).isoformat())
            continue
        if datetime.fromisoformat(due) > now:
            continue
        await storage.set_cooldown_until(tg_id, SE_TAX_KEY, (now + timedelta(days=1)).isoformat())
        message = se_tax_paid(SELF_EMPLOY_TAX) if await storage.spend_zbucks(
            tg_id, SELF_EMPLOY_TAX) else se_tax_fail(SELF_EMPLOY_TAX)
        try:
            await bot.send_message(tg_id, message)
        except Exception:
            pass


async def _process_laundering(bot: Bot, now_iso: str) -> None:
    """Storage сначала фиксирует чистое зачисление, затем идут best-effort сообщения."""
    for settlement in await storage.settle_due_laundering_details(now_iso):
        tg_id, biz, amount = settlement.tg_id, settlement.biz, settlement.amount
        # Отмытые деньги уже зачислены внутри atomic storage-операции.  Здесь
        # остаётся post-commit эквивалент канонического grant(): порог Густава
        # должен увидеть обычный доход, но не зачислить его повторно.
        await maybe_gustav(
            bot, tg_id, settlement.balance_before, settlement.balance_after,
        )
        row = await storage.get_business(tg_id, biz)
        name = biz_display(row[2] if row else None, row[1] if row else 1, biz)
        try:
            await bot.send_message(
                tg_id,
                (f"✨ Отмыв завершён: +{amount} Z чистыми."
                 if biz == BIZ_MOSQUITO else slug_text.launder_done_personal(amount)),
            )
        except Exception:
            pass
        who = await owner_mention(tg_id)
        await announce(
            bot,
            launder_done(who, name, amount) if biz == BIZ_MOSQUITO
            else slug_text.launder_done(who, name, amount),
        )


async def _process_slug_cooking(bot: Bot, now_iso: str) -> None:
    """Выдать готовые изделия после их атомарной фиксации в storage."""
    for tg_id, item, count in await storage.settle_due_slug_cooks(now_iso):
        product = ITEMS.get(item)
        if product is None:
            continue
        suffix = f" ×{count}" if count > 1 else ""
        try:
            await bot.send_message(tg_id, slug_text.cooked(f"{product.emoji} {product.name}{suffix}"))
        except Exception:
            pass
