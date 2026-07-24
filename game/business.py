"""Правила легальных бизнесов и их минутный планировщик."""
import asyncio
import html
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from aiogram import Bot
from aiogram.utils.markdown import hlink

from content import slugs as slug_text
from content import illegal_business as illegal_text
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

# Теневое дело привязано к Комар-фарм Логистикс только в момент покупки.
# Дальше оно живёт в отдельной таблице и не наследует паузу родителя.
BIZ_ILLEGAL_MOSQUITO = "mosquito_escorts"
ILLEGAL_BUSINESS_KEYS = (BIZ_ILLEGAL_MOSQUITO,)

# Комариная логистическая компания.
MOSQUITO_PRICE = 20_000
MOSQUITO_UPKEEP = 200
MOSQUITO_EGGS = (2, 3)
MOSQUITO_CORN = (1, 2)
MOSQUITO_POTATO = (1, 2)
UPGRADE2_PRICE = 15_000
UPGRADE3_PRICE = 20_000
DEFAULT_NAME = "Комар-фарм Логистикс"

# Комарихи-миньетчицы: один уровень, отдельная касса и ежедневная зарплата.
ILLEGAL_MOSQUITO_PRICE = 30_000
ILLEGAL_MOSQUITO_UPKEEP = 300
ILLEGAL_MOSQUITO_PARENT = BIZ_MOSQUITO
ILLEGAL_MOSQUITO_CARD_NAME = "🕳️ Комарихи-миньетчицы"
ILLEGAL_MOSQUITO_NAME = "Комарихи-миньетчицы"
ILLEGAL_MOSQUITO_LEVEL_NAME = "Отсос-бюро «Зззоя»"
ILLEGAL_TIMELINE_EVENT_LIMIT = 10_000

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


@dataclass(frozen=True)
class IllegalBusinessSpec:
    """Неизменяемые параметры одного теневого дела."""

    key: str
    card_name: str
    display_name: str
    level_name: str
    parent_biz: str
    price: int
    upkeep: int


@dataclass(frozen=True)
class IllegalStage:
    """Состояние кассы после успешного очередного часа работы.

    ``theft_chance`` относится к <i>следующей</i> часовой границе.  Поэтому
    первый час (переход из нулевого состояния) всегда проходит без броска,
    а восьмой гарантированно обнуляет кассу на следующей границе.
    """

    hour: int
    income: int
    cash: int
    theft_chance: int
    message: str


IllegalTransitionKind = Literal["advanced", "stolen"]


@dataclass(frozen=True)
class IllegalStageTransition:
    """Чистый результат одной часовой границы теневого бизнеса."""

    kind: IllegalTransitionKind
    from_stage: int
    to_stage: int
    cash_before: int
    cash_after: int
    income: int
    theft_chance: int

    @property
    def stolen(self) -> bool:
        return self.kind == "stolen"


@dataclass(frozen=True)
class IllegalTimelineResult:
    """Снимок теневого бизнеса после безопасного догоняющего расчёта."""

    state: object | None
    summaries: tuple[str, ...]

    def __iter__(self):
        """Позволяет старому простому caller-у распаковать ``state, summaries``."""
        yield self.state
        yield self.summaries


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

ILLEGAL_BUSINESSES = {
    BIZ_ILLEGAL_MOSQUITO: IllegalBusinessSpec(
        key=BIZ_ILLEGAL_MOSQUITO,
        card_name=ILLEGAL_MOSQUITO_CARD_NAME,
        display_name=ILLEGAL_MOSQUITO_NAME,
        level_name=ILLEGAL_MOSQUITO_LEVEL_NAME,
        parent_biz=ILLEGAL_MOSQUITO_PARENT,
        price=ILLEGAL_MOSQUITO_PRICE,
        upkeep=ILLEGAL_MOSQUITO_UPKEEP,
    ),
}

# Касса на каждом этапе — именно накопленная сумма, а не новая независимая
# выплата.  Например, после второго часа в ней 50 + 100 = 150 Z.
ILLEGAL_STAGES = {
    1: IllegalStage(1, 50, 50, 3, illegal_text.stage_message(1)),
    2: IllegalStage(2, 100, 150, 5, illegal_text.stage_message(2)),
    3: IllegalStage(3, 200, 350, 10, illegal_text.stage_message(3)),
    4: IllegalStage(4, 400, 750, 15, illegal_text.stage_message(4)),
    5: IllegalStage(5, 800, 1_550, 30, illegal_text.stage_message(5)),
    6: IllegalStage(6, 1_600, 3_150, 50, illegal_text.stage_message(6)),
    7: IllegalStage(7, 3_200, 6_350, 60, illegal_text.stage_message(7)),
    8: IllegalStage(8, 6_400, 12_750, 100, illegal_text.stage_message(8)),
}
ILLEGAL_MAX_STAGE = max(ILLEGAL_STAGES)


def illegal_business_spec(biz: str) -> IllegalBusinessSpec | None:
    return ILLEGAL_BUSINESSES.get(biz)


def illegal_business_card_name(biz: str) -> str:
    spec = illegal_business_spec(biz)
    return spec.card_name if spec else "Неизвестное теневое дело"


def illegal_business_purchase_price(biz: str) -> int:
    """Цена покупки известного теневого бизнеса.

    Аналог ``business_purchase_price`` намеренно бросает ``KeyError`` для
    неизвестного ключа: callback обязан быть проверен до вызова.
    """
    return ILLEGAL_BUSINESSES[biz].price


def illegal_business_parent(biz: str) -> str:
    return ILLEGAL_BUSINESSES[biz].parent_biz


def illegal_business_upkeep(biz: str) -> int:
    return ILLEGAL_BUSINESSES[biz].upkeep


def illegal_business_display(biz: str) -> str:
    """Единственное название уровня: у теневого дела нет ребрендинга."""
    return ILLEGAL_BUSINESSES[biz].level_name


def illegal_stage(stage: int) -> IllegalStage | None:
    """Данные достигнутого этапа; ``0`` означает ещё пустую кассу."""
    return ILLEGAL_STAGES.get(stage)


def illegal_next_theft_chance(stage: int) -> int:
    """Шанс кражи на следующей границе для текущего этапа."""
    current = illegal_stage(stage)
    return current.theft_chance if current else 0


def illegal_cash_for_stage(stage: int) -> int:
    """Ожидаемая накопленная касса корректного цикла (удобно для UI/tests)."""
    current = illegal_stage(stage)
    return current.cash if current else 0


def illegal_stage_message(stage: int) -> str:
    """Личная реплика текущего часа (включая нейтральный нулевой этап)."""
    current = illegal_stage(stage)
    return current.message if current else illegal_text.stage_message(0)


def advance_illegal_stage(
    stage: int,
    cash: int,
    *,
    roll: int | None = None,
) -> IllegalStageTransition:
    """Чисто рассчитать одну часовую границу.

    Из нулевого состояния открывается первый час и безусловно добавляются
    50 Z.  Из любого уже достигнутого этапа сначала проверяется риск именно
    этого этапа.  При краже вся касса сгорает, а следующий первый час должен
    быть назначен вызывающей стороной через час. ``roll`` используется как
    число от 1 до 100 включительно; 1..chance означает кражу.
    """
    if stage < 0 or stage > ILLEGAL_MAX_STAGE:
        raise ValueError("illegal business stage is out of range")
    if cash < 0:
        raise ValueError("illegal business cash must be non-negative")

    if stage == 0:
        first = ILLEGAL_STAGES[1]
        return IllegalStageTransition(
            "advanced", 0, 1, cash, cash + first.income, first.income, 0,
        )

    current = ILLEGAL_STAGES[stage]
    if roll is None or not 1 <= roll <= 100:
        raise ValueError("roll must be an integer from 1 through 100 after hour one")
    if roll <= current.theft_chance:
        return IllegalStageTransition(
            "stolen", stage, 0, cash, 0, 0, current.theft_chance,
        )

    # Текущий восьмой час имеет риск 100%, но ветка оставлена явной на случай
    # будущих таблиц, где максимальный этап задаётся не 100%-ным шансом.
    if stage >= ILLEGAL_MAX_STAGE:
        return IllegalStageTransition(
            "stolen", stage, 0, cash, 0, 0, current.theft_chance,
        )
    following = ILLEGAL_STAGES[stage + 1]
    return IllegalStageTransition(
        "advanced", stage, following.hour, cash, cash + following.income,
        following.income, current.theft_chance,
    )


# Понятные aliases для callers/tests, которым нужен только чистый расчёт.
illegal_stage_transition = advance_illegal_stage
advance_illegal_business_stage = advance_illegal_stage


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
    await _process_illegal_businesses(bot, now)
    await _process_self_employed_tax(bot, now)
    await _process_laundering(bot, now_iso)
    await _process_slug_cooking(bot, now_iso)


def _illegal_due_identity(entry: object) -> tuple[int, str]:
    """Извлечь владельца и ключ из storage-row без привязки к виду выборки."""
    if hasattr(entry, "tg_id") and hasattr(entry, "biz"):
        return int(entry.tg_id), str(entry.biz)
    if isinstance(entry, dict):
        return int(entry["tg_id"]), str(entry["biz"])
    tg_id, biz = entry  # type: ignore[misc]
    return int(tg_id), str(biz)


def _illegal_status(result: object) -> str:
    """Строковый статус storage-операции или dataclass с таким полем."""
    if isinstance(result, str):
        return result
    return str(getattr(result, "status", "ok"))


async def _send_illegal_updates(bot: Bot | None, tg_id: int,
                                summaries: tuple[str, ...]) -> None:
    """Уведомить владельца только после зафиксированных storage-операций."""
    if bot is None or not summaries:
        return
    if len(summaries) == 1:
        text = summaries[0]
    elif len(summaries) <= 8:
        text = illegal_text.catchup(list(summaries))
    else:
        # После очень долгого простоя не отправляем Telegram-сообщение длиннее
        # лимита: одно сводное уведомление с последними событиями достаточно.
        tail = "\n".join(f"• {line}" for line in summaries[-3:])
        text = (
            f"🕰️ Пока тебя не было, в теневом деле обработано {len(summaries)} событий. "
            f"Последние:\n{tail}"
        )
    try:
        await bot.send_message(tg_id, text)
    except Exception:
        # Уведомление best-effort: деньги и сроки уже сохранены в SQLite.
        pass


async def settle_illegal_timeline(
    bot: Bot | None,
    tg_id: int,
    biz: str,
    now: datetime | None = None,
) -> IllegalTimelineResult:
    """Догнать зарплаты и часы одного теневого бизнеса в строгом порядке.

    Время берётся один раз, поэтому при простое последовательно
    воспроизводятся все прошедшие границы. При одинаковом сроке зарплата
    проходит раньше почасового риска. Неоплата ставит дело на паузу; старые
    часы после неё не доначисляются, а успешная будущая оплата назначает
    первый новый час от реального момента оплаты.

    Storage-операции повторно сверяют ``revision``/срок в economy-транзакции.
    При stale-результате цикл перечитывает строку и не дублирует ни кассу,
    ни зарплату.
    """
    if biz not in ILLEGAL_BUSINESS_KEYS:
        return IllegalTimelineResult(None, ())

    now = now or datetime.now()
    now_iso = now.isoformat()
    summaries: list[str] = []

    # Guard не даёт одной испорченной записи занять scheduler навсегда. При
    # реальном многолетнем простое replay продолжится следующим минутным
    # тиком, не блокируя остальные бизнесы.
    for _ in range(ILLEGAL_TIMELINE_EVENT_LIMIT):
        state = await storage.get_illegal_business(tg_id, biz)
        if state is None:
            final = IllegalTimelineResult(None, tuple(summaries))
            await _send_illegal_updates(bot, tg_id, final.summaries)
            return final

        paused = bool(state.paused)
        upkeep_at = datetime.fromisoformat(state.upkeep_at) if state.upkeep_at else None
        hour_at = datetime.fromisoformat(state.next_hour_at) if state.next_hour_at else None
        upkeep_due = upkeep_at is not None and upkeep_at <= now
        hour_due = not paused and hour_at is not None and hour_at <= now
        if not upkeep_due and not hour_due:
            final = IllegalTimelineResult(state, tuple(summaries))
            await _send_illegal_updates(bot, tg_id, final.summaries)
            return final

        # Совпавшие дедлайны принципиально обслуживаются в этом порядке:
        # сперва зарплата, затем (только если после неё дело не на паузе) час.
        if upkeep_due and (not hour_due or upkeep_at <= hour_at):
            assert upkeep_at is not None
            if paused:
                next_upkeep_at = now + timedelta(days=1)
                resume_hour_at = now + timedelta(hours=1)
            else:
                # Активный бизнес честно догоняет каждый пропущенный день.
                next_upkeep_at = upkeep_at + timedelta(days=1)
                resume_hour_at = None

            settlement = await storage.settle_illegal_upkeep_atomic(
                tg_id,
                biz,
                illegal_business_upkeep(biz),
                now_iso,
                upkeep_at.isoformat(),
                next_upkeep_at.isoformat(),
                resume_hour_at.isoformat() if resume_hour_at else None,
                # Первая неудачная попытка завершает replay: следующая
                # проверка через реальные сутки, а не в следующую минуту из
                # старого просроченного расписания.
                (now + timedelta(days=1)).isoformat(),
            )
            status = _illegal_status(settlement)
            if status in {"not_due", "stale"}:
                continue
            if status == "not_owned":
                final = IllegalTimelineResult(None, tuple(summaries))
                await _send_illegal_updates(bot, tg_id, final.summaries)
                return final
            if status == "paid":
                paid = illegal_text.upkeep_paid(illegal_business_upkeep(biz))
                if paused or bool(getattr(settlement, "was_paused", False)):
                    paid = f"{paid}\n{illegal_text.upkeep_resume()}"
                summaries.append(paid)
                continue
            if status == "unpaid":
                summaries.append(illegal_text.upkeep_fail(illegal_business_upkeep(biz)))
                # Atomic storage already paused it and assigned the following
                # payment date; no old hours may be replayed after this point.
                final_state = await storage.get_illegal_business(tg_id, biz)
                final = IllegalTimelineResult(final_state, tuple(summaries))
                await _send_illegal_updates(bot, tg_id, final.summaries)
                return final
            raise RuntimeError(f"unknown illegal upkeep settlement status: {status}")

        assert hour_at is not None
        stage = int(state.stage)
        transition = advance_illegal_stage(
            stage,
            int(state.accrued),
            roll=random.randint(1, 100) if stage else None,
        )
        # Не ставим час относительно ``now``: после офлайна нужно
        # хронологически проиграть каждый пропущенный риск. После кражи это
        # естественно назначает новый первый час через час после кражи.
        next_hour_at = hour_at + timedelta(hours=1)
        settlement = await storage.advance_illegal_business_atomic(
            tg_id,
            biz,
            state.revision,
            hour_at.isoformat(),
            transition.to_stage,
            transition.cash_after,
            next_hour_at.isoformat(),
            now_iso,
        )
        status = _illegal_status(settlement)
        if status in {"not_due", "stale", "paused", "upkeep_due"}:
            continue
        if status == "not_owned":
            final = IllegalTimelineResult(None, tuple(summaries))
            await _send_illegal_updates(bot, tg_id, final.summaries)
            return final
        if status not in {"ok", "advanced", "stolen"}:
            raise RuntimeError(f"unknown illegal hourly settlement status: {status}")

        if transition.stolen:
            summaries.append(illegal_text.theft(transition.cash_before))
        else:
            summaries.append(illegal_stage_message(transition.to_stage))

    state = await storage.get_illegal_business(tg_id, biz)
    log.warning("Теневой бизнес %s/%s ещё догоняет историю после %d событий",
                tg_id, biz, ILLEGAL_TIMELINE_EVENT_LIMIT)
    final = IllegalTimelineResult(state, tuple(summaries))
    await _send_illegal_updates(bot, tg_id, final.summaries)
    return final


async def _process_illegal_businesses(bot: Bot, now: datetime) -> None:
    """Обслужить только строки, у которых наступил час или зарплата."""
    for entry in await storage.due_illegal_businesses(now.isoformat()):
        tg_id, biz = _illegal_due_identity(entry)
        try:
            await settle_illegal_timeline(bot, tg_id, biz, now)
        except Exception:
            # Одна повреждённая дата не должна останавливать остальных
            # владельцев; следующая минута повторит только проблемную строку.
            log.exception("Теневой бизнес: ошибка таймлайна %s/%s", tg_id, biz)


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
