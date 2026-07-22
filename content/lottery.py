"""Тексты экранов лотереи."""
from datetime import datetime


def _number(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _deadline(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%d.%m.%Y в %H:%M")
    except (TypeError, ValueError):
        return "скоро (бухгалтер потерял календарь)"


def _countdown(closes_at: str, now: datetime) -> str:
    try:
        seconds = max(0, int((datetime.fromisoformat(closes_at) - now).total_seconds()))
    except (TypeError, ValueError):
        return "неизвестно"
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}ч {minutes}м {seconds}с"


def _chance(own_tickets: int, total_tickets: int) -> str:
    if own_tickets <= 0 or total_tickets <= 0:
        return "0%"
    chance = own_tickets * 100 / total_tickets
    if chance < 0.01:
        return "&lt;0,01%"
    return f"{chance:.2f}".rstrip("0").rstrip(".").replace(".", ",") + "%"


def _percent(basis_points: int) -> str:
    value = basis_points / 100
    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",") + "%"


def round_screen(view, now: datetime, *, sales_closed: bool) -> str:
    """Собрать экран активного тиража из read-only snapshot storage."""
    state = (
        "\n\n⏳ Приём билетов уже закрыт. Барабан считает шарики..."
        if sales_closed
        else "\n\nКаждый билет — отдельный шанс. Богатство близко, математика против."
    )
    return (
        f"🎟 <b>Лотерея №{view.round_id}</b>\n\n"
        f"🕛 Розыгрыш: <b>{_deadline(view.closes_at)}</b>\n"
        f"⏳ Осталось: <b>{_countdown(view.closes_at, now)}</b>\n\n"
        f"🎫 Билет: <b>{_number(view.ticket_price)} Z</b>\n"
        f"🎟 Всего билетов: <b>{_number(view.total_tickets)}</b>\n"
        f"🫵 Твоих билетов: <b>{_number(view.own_tickets)}</b>\n"
        f"🏦 Банк: <b>{_number(view.gross_pool)} Z</b>\n"
        f"🏆 Приз после комиссии {_percent(view.fee_bps)}: "
        f"<b>{_number(view.prize_amount)} Z</b>\n"
        f"🎯 Твой шанс: <b>{_chance(view.own_tickets, view.total_tickets)}</b>\n"
        f"💰 Баланс: <b>{_number(view.balance)} Z</b>"
        f"{state}"
    )


def no_active_round() -> str:
    return (
        "🎟 <b>Лотерея</b>\n\n"
        "Тиража пока нет. Видимо, лототрон ушёл покурить — обнови экран чуть позже."
    )


def expired_tickets(count: int) -> str:
    return (
        "🧾 <b>Протухшие билетики</b>\n\n"
        f"В архиве: <b>{_number(count)}</b>\n\n"
        "Они уже сыграли и больше ничего не выиграют, зато отлично напоминают, "
        "что надежда стоила 50 Z. Выбрасывать историю мы не будем."
    )
