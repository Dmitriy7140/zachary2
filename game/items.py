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
}


def shop_items() -> list[Item]:
    """Предметы, доступные к покупке."""
    return [it for it in ITEMS.values() if it.price is not None]


def sellable_items() -> list[Item]:
    """Предметы, которые можно продать на рынке."""
    return [it for it in ITEMS.values() if it.sell_minutes_per_z > 0]
