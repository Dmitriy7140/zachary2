"""Реестр предметов. На наличии предметов завязаны проверки в мини-играх."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    key: str
    name: str
    emoji: str
    max_qty: int
    price: int | None = None       # None = не продаётся в магазине
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
}


def shop_items() -> list[Item]:
    """Предметы, доступные к покупке."""
    return [it for it in ITEMS.values() if it.price is not None]


def sellable_items() -> list[Item]:
    """Предметы, которые можно продать на рынке."""
    return [it for it in ITEMS.values() if it.sell_minutes_per_z > 0]
