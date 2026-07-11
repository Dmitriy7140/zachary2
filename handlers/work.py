"""Раздел «Работа»: Легальная (заглушка) и Нелегальная → Вор."""
import random
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.markdown import hlink

from content import thief as txt
from db import storage
from game.cashier import level_name as cashier_level_name
from game.cars import flex_line
from game.debts import chepushila_days_left, is_chepushila
from game.taxman import grant
from game.thief import (MIN_TARGET_WEALTH, THEFT_THRESHOLDS, is_fail, roll_quality,
                        steal_amount, thief_level)
from utils.guards import ensure_owner, with_owner
from utils.notify import announce
from utils.pagination import page_slice
from utils.photo import show_photo_menu, show_text_menu

WORK_PHOTO = "static/work.png"
WORK_LEGAL_PHOTO = "static/work_legal.png"
WORK_ILLEGAL_PHOTO = "static/work_illegal.png"

router = Router()

VICTIMS_PAGE_SIZE = 6

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
    level = thief_level(thefts)
    lines = [
        "🕶 <b>Нелегальная работа</b> · 🦹 Вор",
        f"Ранг: <b>{txt.LEVEL_NAMES[level - 1]}</b> · удачных краж: {thefts}",
        "Со 2 уровня сам выбираешь, кого щипать.",
        "",
        "<b>Прогрессия:</b>",
    ]
    for i, name in enumerate(txt.LEVEL_NAMES, start=1):
        need = THEFT_THRESHOLDS[i - 1]
        mark = "▶️" if i == level else "▪️"
        req = "" if need == 0 else f" — {need} краж"
        lines.append(f"{mark} {i}. {name}{req}")

    rows = [
        [InlineKeyboardButton(text="🦹 Залезть в карман", callback_data=with_owner("thief:steal", owner))],
        # мошенник и впн — только в личке, без owner
        [InlineKeyboardButton(text="📞 Телефонный мошенник", callback_data="scammer:start")],
        [InlineKeyboardButton(text="🌐 Продавец «VPN-а»", callback_data="vpn:start")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=with_owner("menu:work", owner))],
    ]
    # нелегалка — фото трущоб; переход с фото работ = смена медиа, не пересылка
    await show_photo_menu(cb.message, WORK_ILLEGAL_PHOTO, "work_illegal_photo_id",
                          "\n".join(lines), _kb(rows))
    await cb.answer()


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
                                      callback_data=with_owner("work:illegal", owner))])
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
    back = _back(tg_id, "menu:work")

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
