"""Реестр предметов. На наличии предметов завязаны проверки в мини-играх."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    key: str
    name: str
    emoji: str
    max_qty: int
    price: int | None = None       # None = не продаётся в магазине
    blackmarket: bool = False      # продаётся у Фарцовщика, а не в обычном магазине
    # Рынок: диапазон цены и «минут за каждый +1 Z сверх минимума»
    sell_min: int = 0
    sell_max: int = 0
    sell_minutes_per_z: int = 0     # 0 = не продаётся на рынке


ITEMS: dict[str, Item] = {
    "bucket": Item("bucket", "Ведро", "🪣", max_qty=1, price=200),
    "milk_can": Item("milk_can", "Бидон молока", "🥛", max_qty=10,
                     sell_min=30, sell_max=60, sell_minutes_per_z=10),
    # техника (пригодится для будущих работ)
    "iphone": Item("iphone", "Айфон", "📱", max_qty=1, price=2000),
    "samsung": Item("samsung", "Самсунг", "📲", max_qty=1, price=1000),
    "bike": Item("bike", "Велосипед Братан", "🚲", max_qty=1, price=3000),
    # тачки (нужна любая для апгрейда бизнеса до 2 ур.; флексим самой дорогой)
    "car_merch": Item("car_merch", "Тачка Мерчердс", "🚗", max_qty=1, price=6999),
    "car_panos": Item("car_panos", "Тачка Панос", "🚙", max_qty=1, price=7999),
    "car_mubiesi": Item("car_mubiesi", "Тачка Мубиеси", "🏎", max_qty=1, price=8999),
    # рыбалка
    "rod": Item("rod", "Удочка", "🎣", max_qty=1, price=500),
    "bait_1": Item("bait_1", "Приманка на 🐟", "🪱", max_qty=99, price=55),
    "bait_2": Item("bait_2", "Приманка на 🐡", "🦐", max_qty=99, price=95),
    "bait_3": Item("bait_3", "Приманка на 🐠", "🦑", max_qty=99, price=205),
    "fish_1": Item("fish_1", "Рыба 🐟", "🐟", max_qty=99,
                   sell_min=80, sell_max=100, sell_minutes_per_z=10),
    "fish_2": Item("fish_2", "Рыба 🐡", "🐡", max_qty=99,
                   sell_min=150, sell_max=200, sell_minutes_per_z=10),
    "fish_3": Item("fish_3", "Рыба 🐠", "🐠", max_qty=99,
                   sell_min=400, sell_max=420, sell_minutes_per_z=10),
    # запрещёнка (Фарцовщик)
    "lockpicks": Item("lockpicks", "Отмычки", "🗝", max_qty=1, price=5000, blackmarket=True),
    "cross": Item("cross", "Православный крест", "✝️", max_qty=1, price=10000, blackmarket=True),
    # продукция бизнесов (пока продаётся на рынке, потом пойдёт в производство)
    "egg": Item("egg", "Яйцо", "🥚", max_qty=99,
                sell_min=20, sell_max=40, sell_minutes_per_z=10),
    "corn": Item("corn", "Кукуруза", "🌽", max_qty=99,
                 sell_min=30, sell_max=50, sell_minutes_per_z=10),
    "potato": Item("potato", "Картофель", "🥔", max_qty=99,
                   sell_min=40, sell_max=60, sell_minutes_per_z=10),
}


def shop_items() -> list[Item]:
    """Предметы обычного магазина."""
    return [it for it in ITEMS.values() if it.price is not None and not it.blackmarket]


def blackmarket_items() -> list[Item]:
    """Запрещённые товары Фарцовщика."""
    return [it for it in ITEMS.values() if it.price is not None and it.blackmarket]


def sellable_items() -> list[Item]:
    """Предметы, которые можно продать на рынке."""
    return [it for it in ITEMS.values() if it.sell_minutes_per_z > 0]
