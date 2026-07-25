"""Статические тексты мини-игры «Куб».

Ключи в этом модуле являются частью сохранённой спецификации поколения.
Значения читаются из каталога живьём: обычная правка текста применяется и к
активному Кубу. Если старую формулировку нужно сохранить, добавляется новый
ключ описания, а существующий ключ не переиспользуется.
"""
from dataclasses import dataclass

from game.cube_catalog import (
    EFFECT_BY_KIND,
    HAZARD_BY_KIND,
    NEUTRAL_DESCRIPTION_KEYS,
    EffectArgKind,
    cube_item_use,
    effect_definition,
)


@dataclass(frozen=True)
class HazardText:
    description: str
    success: str
    wrong_item: str


@dataclass(frozen=True)
class EffectText:
    description: str
    notice: str


ROOM_DESCRIPTIONS: dict[str, str] = {
    "start": (
        "Белая камера гудит ровно и почти дружелюбно. "
        "На полу ещё видны следы тех, кто вошёл раньше."
    ),
    "prize": (
        "В центре комнаты мерцает терминал с единственной надписью: "
        "«ПЕРВЫЙ»."
    ),
    "neutral.white": (
        "Холодный свет дрожит в швах белых панелей. Здесь подозрительно тихо."
    ),
    "neutral.amber": (
        "Янтарные стены медленно теплеют и остывают, будто комната дышит."
    ),
    "neutral.blue": (
        "Синие панели покрыты царапинами. Некоторые похожи на карту, но это вряд ли."
    ),
    "neutral.green": (
        "Под зелёным стеклом бегут кабели, а за ними кто-то явно опаздывает."
    ),
    "neutral.red": (
        "Красный свет включается на полсекунды позже твоего шага. Неприятно."
    ),
    "neutral.violet": (
        "Фиолетовая камера пахнет озоном и очень старым ковролином."
    ),
    "neutral.rust": (
        "На ржавых панелях выцарапано множество чисел. Ни одно не помогает."
    ),
    "neutral.mirror": (
        "Матовые зеркала возвращают отражение с едва заметной задержкой."
    ),
    "anomaly.archive": (
        "Стены забиты кассетами с номерами комнат. Один из соседних сигналов читается."
    ),
    "anomaly.echo": (
        "В центре висит неподвижная звуковая волна. Первый шаг будит разряд."
    ),
    "anomaly.dark": (
        "Свет здесь вязнет в воздухе. Двери видны, но детали тонут в темноте."
    ),
    "anomaly.vector": (
        "Стрелки на панелях сходятся в одной точке. Пространство уже выбрало выход."
    ),
    "anomaly.tunnel": (
        "Противоположные стены совпадают друг с другом и не замечают середины комнаты."
    ),
}


HAZARD_TEXTS: dict[str, HazardText] = {
    "flooded_floor": HazardText(
        description=(
            "Пол скрыт под водой, а между панелями пляшут электрические дуги. "
            "Куб вежливо выплёвывает тебя обратно."
        ),
        success="Вода собрана, искры погасли. Комната открыта для всех.",
        wrong_item=(
            "План «{item} против воды под напряжением» не прошёл технику "
            "безопасности. Куб выплюнул тебя обратно."
        ),
    ),
    "chasm_lever": HazardText(
        description=(
            "Сразу за порогом начинается пропасть. Рычаг мостика торчит на другом краю."
        ),
        success="Леска дотянулась до рычага, мост лёг на место.",
        wrong_item=(
            "План дотянуться до рычага с помощью {item} оказался короче "
            "пропасти. Куб выплюнул тебя обратно."
        ),
    ),
    "mutant_leeches": HazardText(
        description=(
            "По полу катится блестящая колония пиявок. Они уже выбрали тебя обедом."
        ),
        success="Пиявки окружили приманку и забыли про участников Куба.",
        wrong_item=(
            "Пиявки осмотрели {item} и решили, что свежее мясо всё ещё ты. "
            "Куб выплюнул тебя обратно."
        ),
    ),
    "wire_net": HazardText(
        description=(
            "Комната от пола до потолка перетянута натянутой металлической сеткой."
        ),
        success="Сетка разрезана. Получился проход и очень концептуальная лапша.",
        wrong_item=(
            "Сетка посмотрела на {item}, осталась сеткой и слегка укрепилась "
            "морально. Куб выплюнул тебя обратно."
        ),
    ),
    "locked_hatch": HazardText(
        description=(
            "Вместо пола — запертый технический люк. Замок пережил несколько цивилизаций."
        ),
        success="Замок сдался, люк закреплён и больше никого не остановит.",
        wrong_item=(
            "Замок изучил {item}, не нашёл ключевых компетенций и отказал "
            "во входе. Куб выплюнул тебя обратно."
        ),
    ),
    "shark_guard": HazardText(
        description=(
            "Прозрачный тоннель пересекает аквариум. Акула караулит его как вахтёрша."
        ),
        success="Акула ушла за приманкой и временно сняла с себя полномочия.",
        wrong_item=(
            "Акула понюхала {item} и решила, что главное блюдо всё ещё держит "
            "его в руках. Куб выплюнул тебя обратно."
        ),
    ),
    "laser_grid": HazardText(
        description=(
            "Воздух выглядит чистым, но обугленные мухи намекают на невидимую лазерную сеть."
        ),
        success="Капли проявили лучи, и безопасный коридор отмечен для всех.",
        wrong_item=(
            "{item} не проявляет лазеры. Зато лазеры проявляют твою "
            "некомпетентность. Куб выплюнул тебя обратно."
        ),
    ),
    "invisible_cutters": HazardText(
        description=(
            "В комнате что-то тонко свистит. Борозды на стенах заканчиваются слишком ровно."
        ),
        success="Яйцо героически обозначило резаки. Безопасный ритм найден.",
        wrong_item=(
            "Проверка через {item} закончилась научным результатом: идея была "
            "херовая. Куб выплюнул тебя обратно."
        ),
    ),
}


EFFECT_TEXTS: dict[str, EffectText] = {
    "archive": EffectText(
        description=ROOM_DESCRIPTIONS["anomaly.archive"],
        notice="Архив шепчет категорию одной соседней комнаты.",
    ),
    "echo": EffectText(
        description=ROOM_DESCRIPTIONS["anomaly.echo"],
        notice="Разряд отбрасывает тебя назад и навсегда затихает.",
    ),
    "dark": EffectText(
        description=ROOM_DESCRIPTIONS["anomaly.dark"],
        notice="Сигналы дверей расплываются, но сами выходы всё ещё видны.",
    ),
    "vector": EffectText(
        description=ROOM_DESCRIPTIONS["anomaly.vector"],
        notice="Комната складывает расстояние и выбрасывает тебя к отмеченной точке.",
    ),
    "tunnel": EffectText(
        description=ROOM_DESCRIPTIONS["anomaly.tunnel"],
        notice="Фазовый тоннель переносит тебя в связанную комнату.",
    ),
}


def room_description(key: str) -> str:
    """Вернуть сохранённое описание либо нейтральный fallback."""
    return ROOM_DESCRIPTIONS.get(key, ROOM_DESCRIPTIONS["neutral.white"])


def hazard_text(kind: str) -> HazardText:
    """Вернуть текст ловушки; неизвестный ключ означает ошибку спецификации."""
    return HAZARD_TEXTS[kind]


def wrong_hazard_item(kind: str, item: str, *, item_key: str) -> str:
    """Прокомментировать ошибку и явно сообщить о потере выбранного предмета."""
    item_use = cube_item_use(item_key)
    if item_use is None:
        raise KeyError(item_key)
    consequence = (
        f"Расходник «{item}» потрачен впустую и исчез из инвентаря."
        if item_use.is_consumable
        else f"Инструмент «{item}» сломался и исчез из инвентаря."
    )
    return f"{hazard_text(kind).wrong_item.format(item=item)} {consequence}"


def missing_selected_item(item: str) -> str:
    """Не раскрывая ответ, сообщить об исчезнувшем после показа кнопки предмете."""
    return (
        f"Ты полез за {item}, но предмет уже исчез из инвентаря. "
        "Куб не принимает воображаемый реквизит."
    )


def effect_text(kind: str) -> EffectText:
    """Вернуть текст аномалии; неизвестный ключ означает ошибку спецификации."""
    return EFFECT_TEXTS[kind]


def effect_notice(kind: str, effect_arg: str | None = None) -> str:
    """Сформатировать уведомление по декларативному контракту эффекта."""
    definition = effect_definition(kind)
    if definition is None:
        raise KeyError(kind)
    notice = effect_text(definition.key).notice
    if definition.arg_kind is EffectArgKind.TARGET_ROOM_CODE and effect_arg:
        return f"{notice} Цель: комната {effect_arg}."
    return notice


def rules_text(prize_per_participant: int) -> str:
    """Короткие правила для Telegram-экрана (без пользовательских данных)."""
    return (
        "🧊 <b>Правила Куба</b>\n\n"
        "Поле состоит из 16 комнат. Ищи приз, двигайся стрелками и "
        "осматривай соседние комнаты. Одна ловушка обязательно требует "
        "предмет, которого у участников может не оказаться. Предмет придётся "
        "выбрать самому: ошибка вернёт в предыдущую комнату и уничтожит "
        "выбранный предмет. Обезвреженная "
        "ловушка открывается для всех. Первый победитель получает "
        f"<b>{prize_per_participant} Z</b> за каждого участника. "
        "При перестройке взносы не возвращаются."
    )


def winner_announcement(
    winner: str,
    prize_amount: int,
    participant_count: int,
) -> str:
    """Публичный результат; ``winner`` уже должен быть HTML-safe."""
    formatted_prize = f"{prize_amount:,}".replace(",", " ")
    return (
        "🧊🏆 <b>Куб взломан!</b>\n"
        f"{winner} первым добрался до призовой комнаты и унёс "
        f"<b>{formatted_prize} Z</b>.\n"
        f"👥 Участников: <b>{participant_count}</b>.\n\n"
        "Стены перестроились. Остальные могут рассказывать, что почти дошли."
    )


def lobby_invitation(generation_id: int) -> str:
    return (
        f"🧊 <b>Куб #{generation_id} перестроился</b>\n\n"
        "Набор снова открыт. Уведомление не держит место и ничего не "
        "списывает — кто раньше нажал, тот раньше услышал, как закрылась дверь."
    )


# description_key хранится отдельно от mechanical key. Тексты подставляются по
# определениям каталога, поэтому новый ключ не обязан следовать соглашению
# ``hazard.<kind>`` или ``anomaly.<kind>``.
ROOM_DESCRIPTIONS.update(
    {
        definition.description_key: HAZARD_TEXTS[kind].description
        for kind, definition in HAZARD_BY_KIND.items()
        if kind in HAZARD_TEXTS
    }
)
ROOM_DESCRIPTIONS.update(
    {
        definition.description_key: EFFECT_TEXTS[kind].description
        for kind, definition in EFFECT_BY_KIND.items()
        if kind in EFFECT_TEXTS
    }
)


def _validate_room_copy() -> None:
    """Не дать механическому и текстовому каталогам разъехаться."""
    if set(HAZARD_BY_KIND) != set(HAZARD_TEXTS):
        raise RuntimeError("Cube hazard definitions and texts are out of sync")
    if set(EFFECT_BY_KIND) != set(EFFECT_TEXTS):
        raise RuntimeError("Cube effect definitions and texts are out of sync")
    required_descriptions = {
        "start",
        "prize",
        *NEUTRAL_DESCRIPTION_KEYS,
        *(definition.description_key for definition in HAZARD_BY_KIND.values()),
        *(definition.description_key for definition in EFFECT_BY_KIND.values()),
    }
    missing = required_descriptions - set(ROOM_DESCRIPTIONS)
    if missing:
        raise RuntimeError(f"Cube room descriptions are missing: {sorted(missing)}")


_validate_room_copy()
