"""Тексты теневых бизнесов.

Здесь намеренно лежит только пользовательский лор.  Правила роста кассы,
вероятности и таймеры находятся в :mod:`game.business`.
"""
import random


ILLEGAL_LORE = (
    "🦟 <b>Комарихи-миньетчицы</b>\n\n"
    "Теневое дело для владельцев Комар-фарм Логистикс. Комарихи уверяют, "
    "что это очень серьёзная услуга по оптимизации денежного потока. "
    "Бухгалтерия почему-то ведётся мешками налички."
)

# Формулировки этапов заданы игровым ТЗ.  Не исправляем даже намеренные
# опечатки: игрок должен видеть именно эти реплики.
STAGE_MESSAGES = {
    1: "Сосут сосут, все ок. Ничего не предвещает беды",
    2: "Дело пока идет, сосут. Проблем не предвидется.",
    3: "Сосут, изредка косятся на наличку. Но изредка",
    4: "Сосут, периодически оглядываясь на стопку налички. Стоит ли забирать?",
    5: "Сосут, сравнительно часто оглядываясь на стопки налика. Забрать, или рискнуть?",
    6: "Сосут почти не отрывая взгляда от мешков с баблом. Может, все-таки еще подождать?",
    7: "Уже почти не сосут, скорее витают над баблом. Пойти ли на последний риск?",
    8: "Срочно хватай бабло, они перестали сосать и летят на твои стопки налика, больше рисковать нельзя!",
}

_BOUGHT = [
    "🕳️ {who} открыл теневое дело при {parent}: {biz} за {price} Z. Бухгалтерия сразу исчезла.",
    "🕳️ {who} вложил {price} Z в {biz}. Комарихи уже смотрят на кассу слишком внимательно.",
]

_UPKEEP_PAID = [
    "🧾 Комарихи получили зарплату: −{amount} Z. Пока что они сосут по графику.",
    "🧾 −{amount} Z на зарплаты комарихам. Мешки с наличкой временно в безопасности.",
]

_UPKEEP_FAIL = [
    "⛔ На зарплаты комарихам не хватило {amount} Z. Они прекратили работу и караулят кассу до оплаты.",
]

_UPKEEP_RESUME = [
    "✅ Зарплата нашлась. Комарихи вернулись к работе; следующий час начнётся заново.",
]

_THEFT = [
    "💸 Комарихи стырили всю кассу — {amount} Z. Пищат, что это был социальный пакет.",
    "💸 Мешки с {amount} Z улетели вместе с комарихами. В кассе осталась только записка: «ну бывает».",
]

_COLLECTED_PERSONAL = [
    "💰 Ты забрал {amount} Z грязными. Комарихи недовольно прожужжали и начали новый час с нуля.",
]

_COLLECTED_THREAD = [
    "💰 {who} забрал из {biz} подозрительно тяжёлую кассу. Комарихи делают вид, что ничего не было.",
]


def stage_message(stage: int) -> str:
    """Точная реплика для достигнутого часа, либо нейтральный старт цикла."""
    return STAGE_MESSAGES.get(stage, "Комарихи ждут первый час работы. Касса пока пуста.")


def bought(who: str, parent: str, biz: str, price: int) -> str:
    return random.choice(_BOUGHT).format(who=who, parent=parent, biz=biz, price=price)


def upkeep_paid(amount: int) -> str:
    return random.choice(_UPKEEP_PAID).format(amount=amount)


def upkeep_fail(amount: int) -> str:
    return random.choice(_UPKEEP_FAIL).format(amount=amount)


def upkeep_resume() -> str:
    return random.choice(_UPKEEP_RESUME)


def theft(amount: int) -> str:
    return random.choice(_THEFT).format(amount=amount)


def collected_personal(amount: int) -> str:
    return random.choice(_COLLECTED_PERSONAL).format(amount=amount)


def collected_thread(who: str, biz: str) -> str:
    return random.choice(_COLLECTED_THREAD).format(who=who, biz=biz)


def catchup(summary: list[str]) -> str:
    """Один компактный личный отчёт вместо пачки просроченных уведомлений."""
    if not summary:
        return ""
    return "🕰️ Пока тебя не было, в теневом деле:\n" + "\n".join(
        f"• {line}" for line in summary
    )
