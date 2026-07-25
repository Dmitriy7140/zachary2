"""Реестр предметов. На наличии предметов завязаны проверки в мини-играх."""
from dataclasses import dataclass
from typing import Iterable, Mapping


MARKET_MAX_WAIT_MINUTES = 3 * 60 + 20


@dataclass(frozen=True)
class Item:
    key: str
    name: str
    emoji: str
    max_qty: int
    price: int | None = None       # None = не продаётся в магазине
    blackmarket: bool = False      # продаётся у Фарцовщика, а не в обычном магазине
    # Рынок: диапазон цены. Срок на максимуме общий, см. market_wait_minutes.
    sell_min: int = 0
    sell_max: int = 0


ITEMS: dict[str, Item] = {
    "bucket": Item("bucket", "Ведро", "🪣", max_qty=1, price=200),
    "milk_can": Item("milk_can", "Бидон молока", "🥛", max_qty=10,
                     sell_min=400, sell_max=600),
    # техника (пригодится для будущих работ)
    "iphone": Item("iphone", "Айфон", "📱", max_qty=1, price=2000),
    "samsung": Item("samsung", "Самсунг", "📲", max_qty=1, price=1000),
    "bike": Item("bike", "Велосипед Братан", "🚲", max_qty=1, price=3000),
    # тачки (нужна любая для апгрейда бизнеса до 2 ур.; флексим самой дорогой)
    "car_merch": Item("car_merch", "Тачка Мерчердс", "🚗", max_qty=1, price=6999),
    "car_panos": Item("car_panos", "Тачка Панос", "🚙", max_qty=1, price=7999),
    "car_mubiesi": Item("car_mubiesi", "Тачка Мубиеси", "🏎", max_qty=1, price=8999),
    # нож Ъ — пропуск на кухню (работа «Шеф»)
    "znak": Item("znak", "Нож «Ъ»", "🔪", max_qty=1, price=3500),
    "crowbar": Item("crowbar", "Монтировка", "🔧", max_qty=1, price=4000),
    # рыбалка
    "rod": Item("rod", "Удочка", "🎣", max_qty=1, price=500),
    "bait_1": Item("bait_1", "Черви на 🐟", "🪱", max_qty=99, price=55),
    "bait_2": Item("bait_2", "Черви на 🐡", "🪱", max_qty=99, price=95),
    "bait_3": Item("bait_3", "Черви на 🐠", "🪱", max_qty=99, price=205),
    "fish_1": Item("fish_1", "Рыба 🐟", "🐟", max_qty=99, sell_min=80, sell_max=100),
    "fish_2": Item("fish_2", "Рыба 🐡", "🐡", max_qty=99, sell_min=150, sell_max=200),
    "fish_3": Item("fish_3", "Рыба 🐠", "🐠", max_qty=99, sell_min=400, sell_max=420),
    # запрещёнка (Фарцовщик)
    "lockpicks": Item("lockpicks", "Отмычки", "🗝", max_qty=1, price=5000, blackmarket=True),
    "cross": Item("cross", "Православный крест", "✝️", max_qty=1, price=10000, blackmarket=True),
    # продукция бизнесов (пока продаётся на рынке, потом пойдёт в производство)
    "egg": Item("egg", "Яйцо", "🥚", max_qty=99, sell_min=20, sell_max=40),
    "corn": Item("corn", "Кукуруза", "🌽", max_qty=99, sell_min=30, sell_max=50),
    "potato": Item("potato", "Картофель", "🥔", max_qty=99, sell_min=40, sell_max=60),
    # глиняная «еда» из бистро слизней: купить в обычном магазине нельзя,
    # зато особенно доверчивые капиталисты торгуют ею на рынке.
    "slime_pie": Item("slime_pie", "«Пирожок» с яйцом", "🪨", max_qty=99,
                      sell_min=200, sell_max=230),
    "slime_pita": Item("slime_pita", "«Пита» с кукурузой", "🌮", max_qty=99,
                       sell_min=240, sell_max=270),
    "slime_dranik": Item("slime_dranik", "«Дранник» с картошкой", "🥯", max_qty=99,
                         sell_min=270, sell_max=300),
}


# Порядок определяет и расположение разделов в инвентаре, и стабильную
# раскладку его кнопок. Все физические предметы должны быть перечислены здесь.
INVENTORY_CATEGORIES = (
    ("sins", "😈 Сумка с грехами"),
    ("transport", "🚗 Транспорт"),
    ("food", "🍽️ Продукты"),
    ("tools", "🧰 Инструменты"),
    ("tech", "📱 Техника"),
)

ITEM_CATEGORY: dict[str, str] = {
    "bucket": "tools",
    "milk_can": "food",
    "iphone": "tech",
    "samsung": "tech",
    "bike": "transport",
    "car_merch": "transport",
    "car_panos": "transport",
    "car_mubiesi": "transport",
    "znak": "tools",
    "crowbar": "tools",
    "rod": "tools",
    "bait_1": "tools",
    "bait_2": "tools",
    "bait_3": "tools",
    "fish_1": "food",
    "fish_2": "food",
    "fish_3": "food",
    "lockpicks": "sins",
    "cross": "sins",
    "egg": "food",
    "corn": "food",
    "potato": "food",
    "slime_pie": "food",
    "slime_pita": "food",
    "slime_dranik": "food",
}

INVENTORY_CATEGORY_LABELS = dict(INVENTORY_CATEGORIES)


def categorized_items(items: Iterable[Item]) -> dict[str, list[Item]]:
    """Разложить известные предметы по разделам в переданном порядке."""
    categories = {key: [] for key, _label in INVENTORY_CATEGORIES}
    for item in items:
        categories[ITEM_CATEGORY[item.key]].append(item)
    return categories


def categorized_inventory_items(items: Mapping[str, int]) -> dict[str, list[tuple[str, int]]]:
    """Вернуть имеющиеся обычные предметы, разложенные по разделам инвентаря.

    Порядок внутри раздела берётся из ``ITEMS``, а не из порядка строк SQLite.
    Лотерейные билеты живут в отдельной таблице и добавляются интерфейсом в
    раздел ``sins``.
    """
    categories = {key: [] for key, _label in INVENTORY_CATEGORIES}
    for key in ITEMS:
        qty = items.get(key, 0)
        if qty <= 0:
            continue
        category = ITEM_CATEGORY[key]
        categories[category].append((key, qty))
    return categories


def market_wait_minutes(item: Item, price: int) -> int:
    """Срок продажи по линейной шкале конкретного продукта.

    Минимальная цена продаётся сразу, а максимальная всегда ждёт ровно
    ``MARKET_MAX_WAIT_MINUTES``. У предметов с разной шириной диапазона цены
    получается свой коэффициент прироста времени.
    """
    if item.sell_max <= item.sell_min:
        raise ValueError(f"{item.key} is not market-sellable")
    if not item.sell_min <= price <= item.sell_max:
        raise ValueError(f"price {price} is outside {item.key} market range")
    price_offset = price - item.sell_min
    price_range = item.sell_max - item.sell_min
    return price_offset * MARKET_MAX_WAIT_MINUTES // price_range


def shop_items() -> list[Item]:
    """Предметы обычного магазина."""
    return [it for it in ITEMS.values() if it.price is not None and not it.blackmarket]


def blackmarket_items() -> list[Item]:
    """Запрещённые товары Фарцовщика."""
    return [it for it in ITEMS.values() if it.price is not None and it.blackmarket]


def sellable_items() -> list[Item]:
    """Предметы, которые можно продать на рынке."""
    return [it for it in ITEMS.values() if it.sell_max > it.sell_min]
