"""Реестр предметов. На наличии предметов завязаны проверки в мини-играх."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    key: str
    name: str
    emoji: str
    max_qty: int
    price: int | None = None  # None = не продаётся в магазине


ITEMS: dict[str, Item] = {
    "bucket": Item("bucket", "Ведро", "🪣", max_qty=1, price=200),
    "milk_can": Item("milk_can", "Бидон молока", "🥛", max_qty=10),
}


def shop_items() -> list[Item]:
    """Предметы, доступные к покупке."""
    return [it for it in ITEMS.values() if it.price is not None]
