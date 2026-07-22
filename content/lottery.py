"""Тексты экранов лотереи."""
from datetime import datetime


WINNER_NUMBER_CALLS = {
    1: "кол; совсем один",
    2: "лебедь (гусь)",
    3: "трое, на троих",
    4: "стул",
    7: "топор",
    10: "часовой",
    11: "барабанные палочки",
    12: "дюжина",
    13: "чертова дюжина",
    18: "в первый раз",
    20: "лебединое озеро",
    21: "очко",
    22: "гуси-лебеди",
    24: "лебедь на стуле",
    25: "опять двадцать пять",
    27: "лебедь с топором",
    33: "кудри",
    41: "ем один",
    44: "стульчики",
    48: "половинку просим",
    50: "полста",
    55: "перчатки",
    66: "валенки",
    69: "туда-сюда",
    70: "топор в озере",
    77: "топорики",
    80: "бабушка",
    81: "бабка с клюшкой",
    85: "перестройка",
    88: "крендельки",
    89: "дедушкин сосед",
    90: "дедушка",
}


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


def winner_announcement(
    winner: str,
    prize_amount: int,
    ticket_number: int,
) -> str:
    """Подпись к публичной картинке результата лотереи.

    ``winner`` — уже экранированная HTML-ссылка на пользователя.
    Для номеров без переданной пользователем реплики показываем только номер.
    """
    call = WINNER_NUMBER_CALLS.get(ticket_number)
    ticket_line = f"🎱 Выигрышный билет: <b>№{ticket_number}</b>"
    if call:
        ticket_line += f" — «{call}»"
    return (
        "🎱🏆🎟 <b>Пан Жмыжко спешит поздравить победителя!</b>\n"
        f"🏆 Победитель: {winner}\n"
        f"💰 Сумма выигрыша: <b>{_number(prize_amount)} Z</b>\n"
        f"{ticket_line}."
    )


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
