"""Раздел «Работа»: Легальная (заглушка) и Нелегальная → Вор."""
import html
import random
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.markdown import hlink

from content import thief as txt
from db import storage
from game.business import business_card_name, illegal_business_card_name, settle_illegal_timeline
from game.cashier import level_name as cashier_level_name
from game.cars import flex_line
from game.debts import chepushila_days_left, is_chepushila
from game.items import ITEMS
from game.illegal_jobs import scammer_rank, vpn_rank
from game.taxman import grant, maybe_gustav
from game.thief import (MIN_TARGET_WEALTH, THEFT_THRESHOLDS, is_fail, roll_quality,
                        BUSINESS_ROBBERY_COOLDOWN_HOURS,
                        BUSINESS_ROBBERY_EMPTY_COOLDOWN_HOURS,
                        BUSINESS_ROBBERY_MIN_LEVEL, CROWBAR_ITEM,
                        business_robbery_products, steal_amount, thief_level)
from utils.guards import ensure_owner, with_owner
from utils.notify import announce
from utils.pagination import page_slice
from utils.photo import show_photo_menu, show_text_menu

WORK_PHOTO = "static/work.png"
WORK_LEGAL_PHOTO = "static/work_legal.png"
WORK_ILLEGAL_PHOTO = "static/work_illegal.png"

router = Router()

VICTIMS_PAGE_SIZE = 6
BUSINESS_TARGETS_PAGE_SIZE = 6
BUSINESS_ROBBERY_COOLDOWN_KEY = "business_robbery"

# свежеобворованный игрок под защитой: менты кругом, второй раз не сунешься
ROBBED_PROTECT_KEY = "robbed_protect"
ROBBED_PROTECT_HOURS = 8


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _back(owner: int, to: str):
    return _kb([[InlineKeyboardButton(text="⬅️ Назад", callback_data=with_owner(to, owner))]])


@router.callback_query(F.data.startswith("menu:work:"))
async def work_menu(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    owner = cb.from_user.id
    if not await storage.get_profile(owner):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)

    level = thief_level(await storage.get_thefts(owner))
    cgames = await storage.player_stat(owner, "cashier_games")
    lines = ["💼 <b>Работа</b>", ""]
    if await is_chepushila(owner):
        lines.append(f"🤡 <b>Чепушила</b> (~{await chepushila_days_left(owner)} дн) — легалка закрыта")
        lines.append("")
    elif await storage.is_honest(owner):
        lines.append("🎖 <b>Честный человек</b> — +10% к легальной работе")
        lines.append("")
    lines += [
        "<b>Текущие ранги:</b>",
        f"🛒 Кассир — {cashier_level_name(cgames)}",
        f"🦹 Вор — {txt.LEVEL_NAMES[level - 1]}",
    ]
    rows = [
        [InlineKeyboardButton(text="✅ Легальная", callback_data=with_owner("work:legal", owner))],
        [InlineKeyboardButton(text="🕶 Нелегальная", callback_data=with_owner("work:illegal", owner))],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data=with_owner("menu:main", owner))],
    ]
    # корневой экран работы — фото хмурого города
    await show_photo_menu(cb.message, WORK_PHOTO, "work_photo_id",
                          "\n".join(lines), _kb(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("work:legal:"))
async def work_legal(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    owner = cb.from_user.id
    if await is_chepushila(owner):
        days = await chepushila_days_left(owner)
        await show_text_menu(
            cb.message,
            f"🤡 Ты «Чепушила» — легальная работа закрыта ещё ~{days} дн.\nВозвращай долги вовремя!",
            _back(owner, "menu:work"),
        )
        return await cb.answer()

    cgames = await storage.player_stat(owner, "cashier_games")
    rows = [
        [InlineKeyboardButton(text="🛒 Кассир — на смену", callback_data="cashier:start")],
        [InlineKeyboardButton(text="🛵 Курьер", callback_data="courier:menu")],
        [InlineKeyboardButton(text="👨‍🍳 Шеф — на кухню", callback_data="chef:start")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=with_owner("menu:work", owner))],
    ]
    # легалка — фото проспекта; переход с фото работ = смена медиа, не пересылка
    await show_photo_menu(
        cb.message, WORK_LEGAL_PHOTO, "work_legal_photo_id",
        f"✅ <b>Легальная работа</b>\n\n"
        f"🛒 Кассир — ранг: <b>{cashier_level_name(cgames)}</b> (смен: {cgames})\n"
        f"🛵 Курьер — доставка по притчам сломанного навигатора\n"
        f"👨‍🍳 Шеф — кухня странных продуктов (нужен Ъ)",
        _kb(rows),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("work:illegal:"))
async def work_illegal(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    owner = cb.from_user.id
    thefts = await storage.get_thefts(owner)
    thief_job_level = thief_level(thefts)
    scam_successes = await storage.player_stat(owner, "scam_successes")
    vpn_successes = await storage.player_stat(owner, "vpn_successes")
    scam_level, scam = scammer_rank(scam_successes)
    vpn_level, vpn = vpn_rank(vpn_successes)
    lines = [
        "🕶 <b>Нелегальная работа</b>",
        f"<i>«{txt.illegal_work_quote()}»</i>",
        "",
        "<b>Твоя прогрессия:</b>",
        f"🦹 Вор: <b>{thief_job_level} уровень</b>",
        f"📞 Телефонный мошенник: <b>{scam_level} уровень</b>",
        f"🌐 Продавец VPN-а: <b>{vpn_level} уровень</b>",
    ]
    rows = [
        [InlineKeyboardButton(text="🦹 Вор", callback_data=with_owner("thief:menu", owner))],
        # мошенник и впн — только в личке, без owner
        [InlineKeyboardButton(text="📞 Телефонный мошенник", callback_data="scammer:menu")],
        [InlineKeyboardButton(text="🌐 Продавец «VPN-а»", callback_data="vpn:start")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=with_owner("menu:work", owner))],
    ]
    # нелегалка — фото трущоб; переход с фото работ = смена медиа, не пересылка
    await show_photo_menu(cb.message, WORK_ILLEGAL_PHOTO, "work_illegal_photo_id",
                          "\n".join(lines), _kb(rows))
    await cb.answer()


async def _render_thief_menu(message, owner: int) -> None:
    thefts = await storage.get_thefts(owner)
    level = thief_level(thefts)
    total_won = await storage.player_stat(owner, "thief_won")
    best_score = await storage.player_stat(owner, "thief_best_score")
    business_robberies = await storage.player_stat(owner, "business_robberies")
    lines = [
        txt.BUSINESS_MENU,
        "Щипай карманы или, когда дорастёшь, вскрывай чужие предприятия.",
        "",
        f"Ранг: <b>{level}. {txt.LEVEL_NAMES[level - 1]}</b>",
        f"Удачных краж: <b>{thefts}</b>",
        f"Учтённый навар: <b>{total_won} Z</b> · рекорд: <b>{best_score} Z</b>",
        f"Налётов на предприятия: <b>{business_robberies}</b>",
        "",
        "<b>Прогрессия:</b>",
    ]
    for index, name in enumerate(txt.LEVEL_NAMES, start=1):
        need = THEFT_THRESHOLDS[index - 1]
        mark = "▶️" if index == level else "▪️"
        requirement = "" if need == 0 else f" — {need} краж"
        lines.append(f"{mark} {index}. {name}{requirement}")

    business_label = "🏢 Обнести предприятие"
    if level < BUSINESS_ROBBERY_MIN_LEVEL:
        business_label += f" — с {BUSINESS_ROBBERY_MIN_LEVEL} ур."
    rows = [
        [InlineKeyboardButton(text="🦹 Залезть в карман", callback_data=with_owner("thief:steal", owner))],
        [InlineKeyboardButton(text=business_label, callback_data=with_owner("thief:business", owner))],
        [InlineKeyboardButton(text="⬅️ К нелегальным работам",
                              callback_data=with_owner("work:illegal", owner))],
    ]
    await show_photo_menu(
        message, WORK_ILLEGAL_PHOTO, "work_illegal_photo_id", "\n".join(lines), _kb(rows),
    )


@router.callback_query(F.data.startswith("thief:menu:"))
async def thief_menu(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await _render_thief_menu(cb.message, cb.from_user.id)
    await cb.answer()


def _business_target_name(target: storage.BusinessRobberyTarget) -> str:
    if target.is_illegal:
        return illegal_business_card_name(target.biz)
    return target.custom_name or business_card_name(target.biz)


def _cooldown_text(until: str | None) -> str:
    if not until:
        return "скоро"
    left = max(0, int((datetime.fromisoformat(until) - datetime.now()).total_seconds()))
    return f"{left // 3600}ч {(left % 3600) // 60}м"


async def _business_robbery_gate(tg_id: int) -> str | None:
    level = thief_level(await storage.get_thefts(tg_id))
    if level < BUSINESS_ROBBERY_MIN_LEVEL:
        return f"🏢 Предприятия можно обносить только с {BUSINESS_ROBBERY_MIN_LEVEL} уровня вора"
    if await storage.get_item_qty(tg_id, CROWBAR_ITEM) < 1:
        return "🔧 Нужна монтировка — ищи её в магазине за 4 000 Z"
    left = await storage.cooldown_left_secs(tg_id, BUSINESS_ROBBERY_COOLDOWN_KEY)
    if left > 0:
        return f"⏳ После прошлого налёта заляг на дно ещё {left // 3600}ч {(left % 3600) // 60}м"
    return None


async def _render_business_targets(message, thief_tg_id: int, page: int = 0) -> bool:
    targets = await storage.list_business_robbery_targets(thief_tg_id)
    if not targets:
        return False
    chunk, page, pages = page_slice(targets, page, BUSINESS_TARGETS_PAGE_SIZE)
    rows = [
        [InlineKeyboardButton(
            text=f"{_business_target_name(target)} — {target.owner_nick}",
            callback_data=with_owner(
                f"thiefbizpick:{target.owner_tg_id}:{target.biz}", thief_tg_id,
            ),
        )]
        for target in chunk
    ]
    if pages > 1:
        rows.append([
            InlineKeyboardButton(
                text="◀️", callback_data=with_owner(f"thiefbizpg:{(page - 1) % pages}", thief_tg_id),
            ),
            InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"),
            InlineKeyboardButton(
                text="▶️", callback_data=with_owner(f"thiefbizpg:{(page + 1) % pages}", thief_tg_id),
            ),
        ])
    rows.append([InlineKeyboardButton(
        text="⬅️ К вору", callback_data=with_owner("thief:menu", thief_tg_id),
    )])
    await show_text_menu(message, txt.BUSINESS_LIST, _kb(rows))
    return True


async def _find_business_target(
    thief_tg_id: int, owner_tg_id: int, biz: str,
) -> storage.BusinessRobberyTarget | None:
    return next(
        (
            target for target in await storage.list_business_robbery_targets(thief_tg_id)
            if target.owner_tg_id == owner_tg_id and target.biz == biz
        ),
        None,
    )


@router.callback_query(F.data.startswith("thief:business:"))
async def thief_business(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    error = await _business_robbery_gate(cb.from_user.id)
    if error:
        return await cb.answer(error, show_alert=True)
    if not await _render_business_targets(cb.message, cb.from_user.id):
        return await cb.answer("На районе пока нет чужих предприятий 🤷", show_alert=True)
    await cb.answer()


@router.callback_query(F.data.startswith("thiefbizpg:"))
async def thief_business_page(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    error = await _business_robbery_gate(cb.from_user.id)
    if error:
        return await cb.answer(error, show_alert=True)
    page = int(cb.data.split(":")[1])
    if not await _render_business_targets(cb.message, cb.from_user.id, page):
        return await cb.answer("Предприятия уже закрылись или сменили владельца", show_alert=True)
    await cb.answer()


@router.callback_query(F.data.startswith("thiefbizpick:"))
async def thief_business_pick(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    error = await _business_robbery_gate(cb.from_user.id)
    if error:
        return await cb.answer(error, show_alert=True)
    parts = cb.data.split(":")
    if len(parts) < 4:
        return await cb.answer("Цель не найдена", show_alert=True)
    target = await _find_business_target(cb.from_user.id, int(parts[1]), parts[2])
    if not target:
        return await cb.answer("Предприятие уже закрылось или пока недоступно", show_alert=True)
    name = html.escape(_business_target_name(target))
    owner = html.escape(target.owner_nick)
    rows = [
        [InlineKeyboardButton(
            text="✅ Да, обнести",
            callback_data=with_owner(
                f"thiefbizyes:{target.owner_tg_id}:{target.biz}", cb.from_user.id,
            ),
        )],
        [InlineKeyboardButton(
            text="❌ Нет", callback_data=with_owner("thief:business", cb.from_user.id),
        )],
    ]
    await show_text_menu(cb.message, txt.business_confirm(name, owner), _kb(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("thiefbizyes:"))
async def thief_business_yes(cb: CallbackQuery, bot: Bot):
    if not await ensure_owner(cb):
        return
    tg_id = cb.from_user.id
    error = await _business_robbery_gate(tg_id)
    if error:
        return await cb.answer(error, show_alert=True)
    parts = cb.data.split(":")
    if len(parts) < 4:
        return await cb.answer("Цель не найдена", show_alert=True)
    target = await _find_business_target(tg_id, int(parts[1]), parts[2])
    if not target:
        return await cb.answer("Предприятие уже закрылось или пока недоступно", show_alert=True)

    # Касса теневого бизнеса сначала догоняется до текущей часовой границы.
    # Только после этого её можно безопасно выносить одним economy commit.
    if target.is_illegal:
        await settle_illegal_timeline(bot, target.owner_tg_id, target.biz)
        target = await _find_business_target(tg_id, target.owner_tg_id, target.biz)
        if not target:
            return await cb.answer("Теневая контора больше недоступна", show_alert=True)

    now = datetime.now()
    result = await storage.rob_business_atomic(
        tg_id,
        target.owner_tg_id,
        target.biz,
        now_iso=now.isoformat(),
        success_cooldown_until=(now + timedelta(hours=BUSINESS_ROBBERY_COOLDOWN_HOURS)).isoformat(),
        empty_cooldown_until=(now + timedelta(hours=BUSINESS_ROBBERY_EMPTY_COOLDOWN_HOURS)).isoformat(),
        illegal_next_hour_at=(now + timedelta(hours=1)).isoformat(),
        legal_products=() if target.is_illegal else business_robbery_products(target.biz),
    )
    name = html.escape(_business_target_name(target))
    thief = hlink(cb.from_user.full_name, f"tg://user?id={tg_id}")
    back = _back(tg_id, "thief:menu")

    if result.status in {"cooldown", "business_cooldown"}:
        what = "Этот бизнес уже под ментами" if result.status == "business_cooldown" else "Заляг на дно"
        return await cb.answer(f"⏳ {what} ещё {_cooldown_text(result.cooldown_until)}", show_alert=True)
    if result.status == "no_crowbar":
        return await cb.answer("🔧 Монтировку уже потерял — нужна новая из магазина", show_alert=True)
    if result.status in {"target_missing", "secret_locked"}:
        return await cb.answer("Предприятие уже недоступно", show_alert=True)
    if result.status == "illegal_due":
        return await cb.answer("Касса как раз обновляется — нажми «Да» ещё раз через секунду", show_alert=True)
    if result.status == "no_profile":
        return await cb.answer("Профиль пропал — обнови меню", show_alert=True)

    if result.status == "empty":
        message = txt.business_empty(name) + "\nПопробовать снова можно через <b>1ч</b>."
        await show_text_menu(cb.message, message, back)
        await cb.answer()
        return await announce(
            bot,
            f"😞 {thief} припёрся грабить {name}, но там пусто. "
            f"Ушёл домой грустный.\n{proletarian()}",
        )

    if result.balance_before is not None and result.balance_after is not None:
        await maybe_gustav(bot, tg_id, result.balance_before, result.balance_after)

    if result.status in {"robbed_laundered", "robbed_illegal_cash"}:
        message = txt.business_money_loot(name, result.amount)
        loot = f"<b>{result.amount} Z</b>"
    else:
        products = ", ".join(
            f"{ITEMS[item].emoji} {ITEMS[item].name} ×{qty}"
            for item, qty in result.products
        )
        message = txt.business_product_loot(name, products)
        loot = products
    message += "\nЗалечь на дно теперь надо на <b>24ч</b>."
    await show_text_menu(cb.message, message, back)
    await cb.answer()
    await announce(
        bot,
        f"🏢 {thief} обнёс {name} у {html.escape(target.owner_nick)} и вынес {loot}.\n"
        f"{proletarian()}",
    )


@router.callback_query(F.data.startswith("thief:steal:"))
async def thief_steal(cb: CallbackQuery, bot: Bot):
    if not await ensure_owner(cb):
        return
    tg_id = cb.from_user.id
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)

    left = await storage.theft_cooldown_left(tg_id)
    if left > 0:
        return await cb.answer(f"⏳ Залечь на дно ещё {left // 3600}ч {(left % 3600) // 60}м",
                               show_alert=True)

    # со 2 уровня жертву выбираем сами; на 1-м — как повезёт
    if thief_level(await storage.get_thefts(tg_id)) >= 2:
        return await _choose_victim(cb)
    players = await storage.list_other_profiles(tg_id)
    if not players:
        return await cb.answer("Грабить некого — на районе пусто 🤷", show_alert=True)
    random.shuffle(players)
    target = None
    for p in players:  # свежеобворованных пропускаем
        if await storage.cooldown_left_secs(p[0], ROBBED_PROTECT_KEY) == 0:
            target = p
            break
    if not target:
        return await cb.answer("Всех на районе уже обнесли — люди настороже 🤷", show_alert=True)
    await _do_steal(cb, bot, target)


async def _choose_victim(cb: CallbackQuery, page: int = 0) -> None:
    owner = cb.from_user.id
    players = await storage.list_other_profiles(owner)
    if not players:
        return await cb.answer("Грабить некого — на районе пусто 🤷", show_alert=True)

    chunk, page, pages = page_slice(players, page, VICTIMS_PAGE_SIZE)
    # деньги жертв не показываем — щипач работает чуйкой
    rows = [[InlineKeyboardButton(text=f"🎯 {nick}",
                                  callback_data=with_owner(f"thief:pick:{pid}", owner))]
            for pid, nick, _zb in chunk]
    if pages > 1:
        rows.append([
            InlineKeyboardButton(text="◀️",
                                 callback_data=with_owner(f"thiefpg:{(page - 1) % pages}", owner)),
            InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"),
            InlineKeyboardButton(text="▶️",
                                 callback_data=with_owner(f"thiefpg:{(page + 1) % pages}", owner)),
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Назад",
                                      callback_data=with_owner("thief:menu", owner))])
    # приходим с фото-экрана нелегалки — текст пересоздаст сообщение
    await show_text_menu(
        cb.message,
        "🦹 Кого щипаем? Сколько у кого в карманах — не видно, работаем вслепую:",
        _kb(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("thiefpg:"))
async def thief_victims_page(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    await _choose_victim(cb, int(cb.data.split(":")[1]))


@router.callback_query(F.data.startswith("thief:pick:"))
async def thief_pick(cb: CallbackQuery, bot: Bot):
    if not await ensure_owner(cb):
        return
    tg_id = cb.from_user.id
    left = await storage.theft_cooldown_left(tg_id)
    if left > 0:
        return await cb.answer(f"⏳ Залечь на дно ещё {left // 3600}ч {(left % 3600) // 60}м",
                               show_alert=True)
    t_id = int(cb.data.split(":")[2])
    p = await storage.get_profile(t_id)
    if not p or t_id == tg_id:
        return await cb.answer("Цель пропала с района 🤷", show_alert=True)
    protect = await storage.cooldown_left_secs(t_id, ROBBED_PROTECT_KEY)
    if protect > 0:
        return await cb.answer(
            f"🚔 Его уже обчистили — вокруг менты, не подойти ещё "
            f"{protect // 3600}ч {(protect % 3600) // 60}м", show_alert=True)
    await _do_steal(cb, bot, (t_id, p[2], p[3]))


async def _do_steal(cb: CallbackQuery, bot: Bot, target: tuple) -> None:
    tg_id = cb.from_user.id
    t_id, t_nick, t_wealth = target
    t_wealth -= await storage.hidden_now(t_id)  # спрятанное в носках не украсть
    thief = hlink(cb.from_user.full_name, f"tg://user?id={tg_id}")
    back = _back(tg_id, "thief:menu")

    # нищая цель — совесть взыграла
    if t_wealth <= MIN_TARGET_WEALTH:
        await storage.set_theft_cooldown(tg_id, 1)
        await show_text_menu(cb.message, txt.POOR.format(target=t_nick), back)
        await cb.answer()
        return await announce(bot, txt.poor_chat(thief, t_nick))

    level = thief_level(await storage.get_thefts(tg_id))
    reduction = 5 if await storage.get_item_qty(tg_id, "lockpicks") > 0 else 0  # отмычки

    # провал
    if is_fail(level, reduction):
        await storage.set_theft_cooldown(tg_id, 1)
        await show_text_menu(cb.message, "🦹 " + txt.fail(t_nick), back)
        await cb.answer()
        return await announce(bot, txt.fail_chat(thief, t_nick))

    # успех — крадём РЕАЛЬНЫЕ деньги у цели
    quality = roll_quality(level)
    amount = steal_amount(quality, t_wealth, level)
    await storage.spend_zbucks(t_id, amount)   # у жертвы реально пропадает
    await grant(bot, tg_id, amount, dirty=True)  # краденое — грязные деньги
    await storage.add_theft(tg_id)
    await storage.bump(tg_id, "thief_won", amount)
    await storage.set_stat_max(tg_id, "thief_best_score", amount)
    await storage.bump(t_id, "robbed")
    # жертва под защитой: 8 часов её никто не обворует
    await storage.set_cooldown_until(
        t_id, ROBBED_PROTECT_KEY,
        (datetime.now() + timedelta(hours=ROBBED_PROTECT_HOURS)).isoformat())
    await storage.set_theft_cooldown(tg_id, 12)
    await show_text_menu(
        cb.message,
        f"<b>{txt.QUALITY_NAMES[quality]}</b>\n\n{txt.success(quality, t_nick, amount)}",
        back,
    )
    await cb.answer()
    await announce(bot, txt.success_chat(quality, thief, t_nick)
                   + await flex_line(tg_id))
