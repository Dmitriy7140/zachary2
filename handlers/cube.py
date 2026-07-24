"""Telegram-интерфейс общей мини-игры «Куб».

Callback хранит только поколение, версию хода и направление/цель. Любое
авторитетное состояние повторно читается и проверяется в storage.
"""
import html
import logging
import re
import secrets
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from config import config
from content import cube as cube_content
from db import storage
from game.cube import new_cube_spec
from game.items import ITEMS
from utils.guards import ensure_private, with_owner
from utils.photo import show_screen

log = logging.getLogger(__name__)
router = Router()

_POSITIVE_INT_RE = re.compile(r"[1-9][0-9]*")
_NONNEGATIVE_INT_RE = re.compile(r"(?:0|[1-9][0-9]*)")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{11}")
_DIRECTIONS = ("n", "e", "s", "w")
_DIRECTION_LABELS = {
    "n": "⬆️ Вперёд",
    "e": "➡️ Вправо",
    "s": "⬇️ Назад",
    "w": "⬅️ Влево",
}
_CATEGORY_LABELS = {
    "calm": "спокойно",
    "quiet": "спокойно",
    "neutral": "спокойно",
    "start": "спокойно",
    "prize": "сигнал не читается",
    "hazard": "предметная ловушка",
    "anomaly": "аномалия",
    "unknown": "сигнал не читается",
    "unreadable": "сигнал не читается",
}


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _positive_int(value: str) -> int | None:
    if _POSITIVE_INT_RE.fullmatch(value) is None:
        return None
    return int(value)


def _nonnegative_int(value: str) -> int | None:
    if _NONNEGATIVE_INT_RE.fullmatch(value) is None:
        return None
    return int(value)


def _callback_data(value: str) -> str:
    if len(value.encode("utf-8")) > 64:
        raise ValueError("cube callback_data exceeds Telegram's 64-byte limit")
    return value


def _generation_arg(data: str | None, action: str) -> int | None:
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[:2] != ["c", action]:
        return None
    return _positive_int(parts[2])


def _entry_args(data: str | None) -> tuple[int, str] | None:
    parts = (data or "").split(":")
    if len(parts) != 4 or parts[:2] != ["c", "e"]:
        return None
    generation_id = _positive_int(parts[2])
    if generation_id is None or _TOKEN_RE.fullmatch(parts[3]) is None:
        return None
    return generation_id, parts[3]


def _versioned_direction_args(
    data: str | None, action: str
) -> tuple[int, int, str] | None:
    parts = (data or "").split(":")
    if len(parts) != 5 or parts[:2] != ["c", action]:
        return None
    generation_id = _positive_int(parts[2])
    version = _nonnegative_int(parts[3])
    direction = parts[4]
    if generation_id is None or version is None or direction not in _DIRECTIONS:
        return None
    return generation_id, version, direction


def _look_args(data: str | None) -> tuple[int, int] | None:
    parts = (data or "").split(":")
    if len(parts) != 4 or parts[:2] != ["c", "o"]:
        return None
    generation_id = _positive_int(parts[2])
    version = _nonnegative_int(parts[3])
    if generation_id is None or version is None:
        return None
    return generation_id, version


def _action_args(data: str | None) -> tuple[int, int, int] | None:
    parts = (data or "").split(":")
    if len(parts) != 5 or parts[:2] != ["c", "a"]:
        return None
    generation_id = _positive_int(parts[2])
    version = _nonnegative_int(parts[3])
    room_id = _nonnegative_int(parts[4])
    if generation_id is None or version is None or room_id is None:
        return None
    return generation_id, version, room_id


def _subscribe_args(data: str | None) -> tuple[int, str] | None:
    parts = (data or "").split(":")
    if len(parts) != 4 or parts[:2] != ["c", "ns"]:
        return None
    generation_id = _positive_int(parts[2])
    if generation_id is None or _TOKEN_RE.fullmatch(parts[3]) is None:
        return None
    return generation_id, parts[3]


def _cancel_args(data: str | None) -> tuple[int, int] | None:
    parts = (data or "").split(":")
    if len(parts) != 4 or parts[:2] != ["c", "nc"]:
        return None
    generation_id = _positive_int(parts[2])
    subscription_id = _positive_int(parts[3])
    if generation_id is None or subscription_id is None:
        return None
    return generation_id, subscription_id


def _next_spec():
    return new_cube_spec()


async def _ensure_cube_private(cb: CallbackQuery) -> bool:
    message = cb.message
    if message is None or message.chat.type != ChatType.PRIVATE:
        await cb.answer("Куб открывается только в личке бота 🧊", show_alert=True)
        return False
    # Сохраняем общий guard как единую точку проверки private callback.
    return await ensure_private(cb)


async def _advance() -> None:
    await storage.advance_cube_lifecycle(_next_spec())


def _seconds_left(value: str | None) -> int | None:
    if not value:
        return None
    try:
        target = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    now = (
        datetime.now(target.tzinfo)
        if target.tzinfo is not None
        else datetime.now(timezone.utc).replace(tzinfo=None)
    )
    return max(0, int((target - now).total_seconds()))


def _duration(value: str | None) -> str:
    seconds = _seconds_left(value)
    if seconds is None:
        return "—"
    minutes, second = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f"{hours}:{minute:02d}:{second:02d}" if hours else f"{minute}:{second:02d}"


def _room_description(key: str | None) -> str:
    if key:
        try:
            return cube_content.room_description(key)
        except KeyError:
            pass
    return "Холодный свет дрожит в швах металлических панелей."


def _hazard_description(kind: str | None) -> str:
    if kind:
        try:
            return cube_content.hazard_text(kind).description
        except KeyError:
            pass
    return "Комната встречает тебя работающей ловушкой и выталкивает обратно."


def _hazard_action(
    kind: str | None, item_key: str | None, consume_qty: int
) -> str:
    if kind:
        try:
            return cube_content.hazard_text(kind).action
        except KeyError:
            pass
    suffix = " (−1)" if consume_qty else ""
    return f"Обезвредить с помощью {_item_label(item_key)}{suffix}"


def _hazard_result(kind: str | None, field: str, fallback: str) -> str:
    if kind:
        try:
            return str(getattr(cube_content.hazard_text(kind), field))
        except (AttributeError, KeyError):
            pass
    return fallback


def _effect_notice(kind: str | None, effect_arg: str | None = None) -> str | None:
    if not kind:
        return None
    try:
        notice = cube_content.effect_text(kind).notice
    except KeyError:
        return None
    if kind in {"vector", "tunnel"} and effect_arg:
        return f"{notice} Цель: комната {effect_arg}."
    return notice


def _item_label(item_key: str | None) -> str:
    item = ITEMS.get(item_key or "")
    return f"{item.emoji} {item.name}" if item else "нужный предмет"


def _category_label(category: str | None) -> str:
    return _CATEGORY_LABELS.get(category or "unknown", "сигнал не читается")


def _direction_map(view) -> dict[str, object]:
    return {direction.direction: direction for direction in view.directions}


def _direction_button(view, direction: str, *, observe: bool = False):
    direction_view = _direction_map(view).get(direction)
    if direction_view is None or not direction_view.exists:
        return InlineKeyboardButton(text="·", callback_data="c:x")

    label = _DIRECTION_LABELS[direction]
    if direction_view.hazard_active:
        label = f"⚠️ {label}"
    if direction_view.room_code:
        label = f"{label} · {direction_view.room_code}"
    action = "o" if observe else "m"
    return InlineKeyboardButton(
        text=label,
        callback_data=_callback_data(
            f"c:{action}:{view.generation_id}:{view.run_version}:{direction}"
        ),
    )


def _known_directions(view) -> list[str]:
    lines = []
    for direction in view.directions:
        if not direction.exists or (
            not direction.room_code and not direction.category
        ):
            continue
        label = _DIRECTION_LABELS.get(direction.direction, direction.direction)
        category = _category_label(direction.category)
        room = direction.room_code or "неизвестная комната"
        lines.append(f"{label}: {room} · {category}")
    return lines


def _room_keyboard(view, tg_id: int, *, observe: bool = False):
    if observe:
        rows = [
            [_direction_button(view, "n", observe=True)],
            [
                _direction_button(view, "w", observe=True),
                InlineKeyboardButton(
                    text="↩️ В комнату",
                    callback_data=_callback_data(f"c:v:{view.generation_id}"),
                ),
                _direction_button(view, "e", observe=True),
            ],
            [_direction_button(view, "s", observe=True)],
        ]
    else:
        rows = [
            [_direction_button(view, "n")],
            [
                _direction_button(view, "w"),
                InlineKeyboardButton(
                    text="👁 Осмотреть",
                    callback_data=_callback_data(
                        f"c:o:{view.generation_id}:{view.run_version}"
                    ),
                ),
                _direction_button(view, "e"),
            ],
            [_direction_button(view, "s")],
        ]

    if not observe and view.pending_hazard_room_id is not None:
        action = _hazard_action(
            view.pending_hazard_kind,
            view.pending_required_item_key,
            int(view.pending_consume_qty or 0),
        )
        rows.append([
            InlineKeyboardButton(
                text=action,
                callback_data=_callback_data(
                    "c:a:"
                    f"{view.generation_id}:{view.run_version}:"
                    f"{view.pending_hazard_room_id}"
                ),
            )
        ])

    rows.extend([
        [InlineKeyboardButton(
            text="🔄 Обновить",
            callback_data=_callback_data(f"c:v:{view.generation_id}"),
        )],
        [InlineKeyboardButton(
            text="⬅️ К мини-играм",
            callback_data=with_owner("menu:games", tg_id),
        )],
    ])
    return _kb(rows)


def _room_text(view, *, observe: bool = False) -> str:
    room_code = view.room_code or "???"
    description = _room_description(view.room_description_key)
    if view.room_hazard_kind:
        description = _hazard_result(
            view.room_hazard_kind,
            "success" if view.room_hazard_resolved else "description",
            description,
        )
    lines = [
        f"🧊 <b>Куб #{view.generation_id} · Комната {room_code}</b>",
        description,
        "",
    ]
    deadline = view.closes_at or view.idle_expires_at
    lines.append(
        f"⏳ {_duration(deadline)} · 👥 {view.participant_count} · "
        f"🏆 {view.prize_amount} Z"
    )
    lines.append(f"Исследовано: {view.explored_count}/16")

    if view.generation_status == "lobby" and view.lobby_closes_at:
        lines.append(f"Набор открыт ещё {_duration(view.lobby_closes_at)}")

    known = _known_directions(view)
    if known:
        lines.extend(["", "<b>Известные направления:</b>", *known])

    if view.pending_hazard_room_id is not None:
        lines.extend([
            "",
            "⚠️ <b>Ловушка в соседней комнате</b>",
            _hazard_description(view.pending_hazard_kind),
            f"Нужен предмет: <b>{_item_label(view.pending_required_item_key)}</b>.",
        ])

    if view.room_hazard_resolved:
        resolver = html.escape(view.room_resolved_by_nick or "другой участник")
        lines.extend([
            "",
            f"✅ Ловушку обезвредил <b>{resolver}</b>. Проход открыт для всех.",
        ])

    if observe:
        lines.extend(["", "👁 Выбери направление для осмотра."])
    return "\n".join(lines)[:1024]


def _lobby_text(view) -> str:
    status_lines = {
        "waiting": "Куб пуст. Первая оплата запустит общий отсчёт.",
        "lobby": f"Набор открыт ещё {_duration(view.lobby_closes_at)}.",
        "active": "Набор закрыт. Исследователи уже внутри.",
    }
    current_prize = int(view.prize_amount or 0)
    after_entry = current_prize + int(view.prize_per_participant)
    lines = [
        f"🧊 <b>Куб #{view.generation_id}</b>",
        status_lines.get(view.generation_status, "Этот Куб уже перестраивается."),
        "",
        f"👥 Участников: {view.participant_count}/{view.max_participants}",
        f"🏆 Джекпот сейчас: {current_prize} Z",
    ]
    if view.generation_status in {"waiting", "lobby"}:
        lines.append(f"После твоего входа: {after_entry} Z")
    deadline = view.closes_at or view.idle_expires_at
    if deadline:
        lines.append(f"⏳ До перестройки: {_duration(deadline)}")
    lines.extend([
        "",
        f"Вход: <b>{view.entry_cost} Z</b> · твой баланс: {view.balance} Z",
        "Внутри обязательно понадобится один неизвестный предмет. "
        "Куб может оказаться непроходимым, а взнос не возвращается.",
    ])
    return "\n".join(lines)[:1024]


def _lobby_keyboard(view, tg_id: int):
    rows = []
    if (
        view.generation_status in {"waiting", "lobby"}
        and view.participant_count < view.max_participants
    ):
        token = secrets.token_urlsafe(8)
        rows.append([
            InlineKeyboardButton(
                text=f"🚪 Войти — {view.entry_cost} Z",
                callback_data=_callback_data(
                    f"c:e:{view.generation_id}:{token}"
                ),
            )
        ])
    elif view.generation_status == "active":
        subscription_id = getattr(view, "subscription_id", None)
        if subscription_id is None:
            token = secrets.token_urlsafe(8)
            rows.append([
                InlineKeyboardButton(
                    text="🔔 Позвать в следующий Куб",
                    callback_data=_callback_data(
                        f"c:ns:{view.generation_id}:{token}"
                    ),
                )
            ])
        else:
            subscription_generation_id = getattr(
                view, "subscription_generation_id", view.generation_id
            )
            rows.append([
                InlineKeyboardButton(
                    text="🔕 Отменить уведомление",
                    callback_data=_callback_data(
                        f"c:nc:{subscription_generation_id}:{subscription_id}"
                    ),
                )
            ])
    rows.extend([
        [InlineKeyboardButton(
            text="📜 Правила", callback_data=f"c:r:{view.generation_id}"
        )],
        [InlineKeyboardButton(
            text="🔄 Обновить", callback_data=f"c:v:{view.generation_id}"
        )],
        [InlineKeyboardButton(
            text="⬅️ К мини-играм", callback_data=with_owner("menu:games", tg_id)
        )],
    ])
    return _kb(rows)


async def _render_current(cb: CallbackQuery, *, observe: bool = False) -> None:
    tg_id = cb.from_user.id
    view = await storage.get_cube_view(tg_id)
    if view is None:
        await show_screen(
            cb.message,
            "🧊 Куб гудит за стеной, но вход пока не собран. Обнови экран.",
            _kb([
                [InlineKeyboardButton(text="🔄 Обновить", callback_data="cube:view")],
                [InlineKeyboardButton(
                    text="⬅️ К мини-играм",
                    callback_data=with_owner("menu:games", tg_id),
                )],
            ]),
        )
        return
    if view.run_status == "active" and view.current_room_id is not None:
        await show_screen(
            cb.message,
            _room_text(view, observe=observe),
            _room_keyboard(view, tg_id, observe=observe),
        )
        return
    await show_screen(cb.message, _lobby_text(view), _lobby_keyboard(view, tg_id))


async def _operation_failed(cb: CallbackQuery, operation: str, exc: Exception) -> None:
    log.exception("Куб: ошибка %s: %s", operation, exc)
    await cb.answer("Куб заклинило. Попробуй обновить экран.", show_alert=True)


async def _closed_generation_notice(
    generation_id: int,
    fallback: str = "Куб уже перестроился.",
) -> str:
    """Вернуть результат старого поколения без доверия данным callback."""
    try:
        winner = await storage.get_cube_winner(generation_id)
    except Exception as exc:
        log.exception("Куб #%s: не удалось прочитать победителя: %s", generation_id, exc)
        return fallback
    if winner is None:
        return fallback
    nick = " ".join(str(winner.winner_nick or "Игрок").split())[:80]
    return (
        f"Куб уже взломал {nick}: {winner.prize_amount} Z. "
        "Открываю новый лабиринт."
    )[:200]


@router.callback_query(F.data == "cube:view")
async def cube_view(cb: CallbackQuery):
    if not await _ensure_cube_private(cb):
        return
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await cb.answer()
    try:
        await _advance()
        await _render_current(cb)
    except Exception as exc:
        log.exception("Куб: не удалось открыть экран: %s", exc)
        await show_screen(cb.message, "🧊 Куб заклинило. Попробуй зайти чуть позже.")


@router.callback_query(F.data.startswith("c:v:"))
async def cube_refresh(cb: CallbackQuery):
    generation_id = _generation_arg(cb.data, "v")
    if generation_id is None:
        return await cb.answer("Кнопка Куба повреждена.", show_alert=True)
    if not await _ensure_cube_private(cb):
        return
    try:
        await _advance()
        view = await storage.get_cube_view(cb.from_user.id)
    except Exception as exc:
        return await _operation_failed(cb, "refresh", exc)
    changed = view is not None and view.generation_id != generation_id
    notice = (
        await _closed_generation_notice(generation_id, "Куб уже перестроился")
        if changed
        else "Обновлено"
    )
    await cb.answer(notice, show_alert=changed)
    await _render_current(cb)


@router.callback_query(F.data.startswith("c:r:"))
async def cube_rules(cb: CallbackQuery):
    generation_id = _generation_arg(cb.data, "r")
    if generation_id is None:
        return await cb.answer("Кнопка Куба повреждена.", show_alert=True)
    if not await _ensure_cube_private(cb):
        return
    await cb.answer()
    try:
        await _advance()
        view = await storage.get_cube_view(cb.from_user.id)
    except Exception as exc:
        log.exception("Куб: не удалось обновить правила: %s", exc)
        view = None
    prize_per_participant = (
        view.prize_per_participant
        if view is not None
        else config.cube_prize_per_participant
    )
    current_generation_id = view.generation_id if view is not None else generation_id
    rules = cube_content.rules_text(prize_per_participant)
    rows = [[InlineKeyboardButton(
        text="↩️ Назад",
        callback_data=_callback_data(f"c:v:{current_generation_id}"),
    )]]
    await show_screen(cb.message, str(rules)[:1024], _kb(rows))


@router.callback_query(F.data.startswith("c:e:"))
async def cube_enter(cb: CallbackQuery):
    args = _entry_args(cb.data)
    if args is None:
        return await cb.answer("Кнопка входа повреждена.", show_alert=True)
    if not await _ensure_cube_private(cb):
        return
    generation_id, request_key = args
    try:
        result = await storage.enter_cube(
            generation_id, cb.from_user.id, request_key, _next_spec()
        )
    except Exception as exc:
        return await _operation_failed(cb, "enter", exc)

    messages = {
        "entered": ("Взнос принят. Дверь за спиной закрылась 🧊", False),
        "resumed": ("Продолжаем с прежней комнаты", False),
        "not_recruiting": ("Набор уже закрыт. Деньги не списаны.", True),
        "full": ("В Кубе уже нет свободных мест. Деньги не списаны.", True),
        "closed": ("Этот Куб уже перестроился. Деньги не списаны.", True),
        "insufficient": ("Не хватает доступных Z для входа.", True),
        "no_profile": ("Сначала зарегистрируйся 😉", True),
        "invalid": ("Эта кнопка входа больше не действует.", True),
    }
    message, alert = messages.get(
        result.status, ("Куб не принял запрос. Деньги не списаны.", True)
    )
    await cb.answer(message, show_alert=alert)
    await _render_current(cb)


@router.callback_query(F.data.startswith("c:o:"))
async def cube_observe(cb: CallbackQuery):
    if not await _ensure_cube_private(cb):
        return
    direction_args = _versioned_direction_args(cb.data, "o")
    if direction_args is None:
        look_args = _look_args(cb.data)
        if look_args is None:
            return await cb.answer("Кнопка осмотра повреждена.", show_alert=True)
        generation_id, version = look_args
        try:
            await _advance()
            view = await storage.get_cube_view(cb.from_user.id)
        except Exception as exc:
            return await _operation_failed(cb, "observe menu", exc)
        if (
            view is None
            or view.generation_id != generation_id
            or view.run_status != "active"
            or view.run_version != version
        ):
            await cb.answer("Комната уже изменилась", show_alert=True)
            return await _render_current(cb)
        await cb.answer("Выбери направление")
        return await _render_current(cb, observe=True)

    generation_id, version, direction = direction_args
    try:
        result = await storage.observe_cube(
            generation_id,
            cb.from_user.id,
            version,
            direction,
            _next_spec(),
        )
    except Exception as exc:
        return await _operation_failed(cb, "observe", exc)
    messages = {
        "observed": f"Сканер говорит: {_category_label(result.category)}.",
        "wall": "За этой панелью нет прохода.",
        "stale": "Ты уже успел сменить позицию.",
        "closed": "Куб уже перестроился.",
        "no_run": "Сначала войди в Куб.",
    }
    message = messages.get(result.status, "Сигнал рассыпался.")
    if result.status == "closed":
        message = await _closed_generation_notice(generation_id, message)
    await cb.answer(message, show_alert=True)
    await _render_current(cb)


@router.callback_query(F.data.startswith("c:m:"))
async def cube_move(cb: CallbackQuery):
    args = _versioned_direction_args(cb.data, "m")
    if args is None:
        return await cb.answer("Кнопка движения повреждена.", show_alert=True)
    if not await _ensure_cube_private(cb):
        return
    generation_id, version, direction = args
    try:
        result = await storage.move_cube(
            generation_id,
            cb.from_user.id,
            version,
            direction,
            _next_spec(),
        )
    except Exception as exc:
        return await _operation_failed(cb, "move", exc)
    messages = {
        "moved": (
            _effect_notice(result.effect_kind, result.effect_arg)
            or "Ты переходишь в следующую комнату.",
            False,
        ),
        "won": (f"Приз найден! Тебе начислено {result.prize_amount} Z 🏆", True),
        "wall": ("Здесь глухая панель.", True),
        "hazard": ("Ловушка отбросила тебя назад. Теперь она раскрыта для всех.", True),
        "bounced": (
            _effect_notice(result.effect_kind, result.effect_arg)
            or "Пространство схлопнулось и выбросило тебя обратно.",
            True,
        ),
        "stale": ("Эта стрелка осталась от прошлого хода.", True),
        "closed": ("Куб уже перестроился.", True),
        "no_run": ("Сначала войди в Куб.", True),
    }
    message, alert = messages.get(result.status, ("Куб не понял направление.", True))
    if result.status == "closed":
        message = await _closed_generation_notice(generation_id, message)
    await cb.answer(message, show_alert=alert)
    await _render_current(cb)


@router.callback_query(F.data.startswith("c:a:"))
async def cube_action(cb: CallbackQuery):
    args = _action_args(cb.data)
    if args is None:
        return await cb.answer("Кнопка действия повреждена.", show_alert=True)
    if not await _ensure_cube_private(cb):
        return
    generation_id, version, room_id = args
    try:
        result = await storage.resolve_cube_hazard_and_enter(
            generation_id,
            cb.from_user.id,
            version,
            room_id,
            _next_spec(),
        )
    except Exception as exc:
        return await _operation_failed(cb, "hazard action", exc)
    item = _item_label(result.required_item_key)
    success = _hazard_result(
        getattr(result, "hazard_kind", None),
        "success",
        f"{item} сработал. Проход открыт для всех!",
    )
    missing = _hazard_result(
        getattr(result, "hazard_kind", None),
        "missing",
        f"Нужен предмет: {item}.",
    )
    messages = {
        "resolved_and_moved": (success, False),
        "already_resolved": ("Ловушку уже отключил другой участник.", True),
        "missing_item": (missing, True),
        "stale": ("Эта кнопка осталась от прошлого хода.", True),
        "closed": ("Куб уже перестроился.", True),
        "no_run": ("Сначала войди в Куб.", True),
        "invalid": ("Из этой комнаты ловушку не достать.", True),
    }
    message, alert = messages.get(result.status, ("Ловушка не отреагировала.", True))
    if result.status == "closed":
        message = await _closed_generation_notice(generation_id, message)
    await cb.answer(message, show_alert=alert)
    await _render_current(cb)


@router.callback_query(F.data.startswith("c:ns:"))
async def cube_subscribe(cb: CallbackQuery):
    args = _subscribe_args(cb.data)
    if args is None:
        return await cb.answer("Кнопка уведомления повреждена.", show_alert=True)
    if not await _ensure_cube_private(cb):
        return
    generation_id, request_key = args
    try:
        result = await storage.subscribe_cube(
            generation_id, cb.from_user.id, request_key, _next_spec()
        )
    except Exception as exc:
        return await _operation_failed(cb, "subscribe", exc)
    messages = {
        "subscribed": "Позову, когда откроется следующий Куб 🔔",
        "already_subscribed": "Ты уже стоишь в списке ожидания.",
        "stale": "Этот Куб уже сменился. Показываю новый.",
        "invalid": "Эта кнопка уведомления больше не действует.",
    }
    await cb.answer(messages.get(result.status, "Не удалось подписаться."), show_alert=True)
    await _render_current(cb)


@router.callback_query(F.data.startswith("c:nc:"))
async def cube_cancel_subscription(cb: CallbackQuery):
    args = _cancel_args(cb.data)
    if args is None:
        return await cb.answer("Кнопка отмены повреждена.", show_alert=True)
    if not await _ensure_cube_private(cb):
        return
    generation_id, subscription_id = args
    try:
        result = await storage.cancel_cube_subscription(
            generation_id,
            cb.from_user.id,
            subscription_id,
            _next_spec(),
        )
    except Exception as exc:
        return await _operation_failed(cb, "cancel subscription", exc)
    messages = {
        "cancelled": "Уведомление отменено.",
        "stale": "Эта подписка уже изменилась.",
        "invalid": "Такой подписки больше нет.",
    }
    await cb.answer(messages.get(result.status, "Не удалось отменить уведомление."), show_alert=True)
    await _render_current(cb)


@router.callback_query(F.data == "c:x")
async def cube_noop(cb: CallbackQuery):
    if not await _ensure_cube_private(cb):
        return
    await cb.answer("Там глухая стена.")
