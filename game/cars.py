"""Тачки: понты, флекс в треде и пропуск к апгрейду бизнеса.

Любое уведомление «игрок отработал» дополняется флексом его тачкой.
Если тачек несколько — флексим самой дорогой (Мубиеси > Панос > Мерчердс).
"""
import random

from db import storage
from game.items import ITEMS

# от самой понтовой к простой
CARS = ["car_mubiesi", "car_panos", "car_merch"]

_FLEX = [
    " У него, кстати, есть {car} — он купил её, чтобы все завидовали.",
    " С места событий укатил на {car}. Понтово.",
    " Кстати, у него {car}. Завидуйте.",
    " Погудел клаксоном {car} и уехал в закат.",
    " Всё это время его {car} стояла рядом на аварийке. Красиво жить не запретишь.",
    " Домой, разумеется, поехал на {car} — чтоб все видели.",
]


async def best_car(tg_id: int) -> str | None:
    """Ключ самой понтовой тачки игрока или None."""
    for key in CARS:
        if await storage.get_item_qty(tg_id, key) > 0:
            return key
    return None


async def has_car(tg_id: int) -> bool:
    return await best_car(tg_id) is not None


async def flex_line(tg_id: int) -> str:
    """Хвост для тредового уведомления («…и скрылся на Тачке Мубиеси»). Пусто без тачки."""
    key = await best_car(tg_id)
    if not key:
        return ""
    it = ITEMS[key]
    return random.choice(_FLEX).format(car=f"{it.emoji} {it.name}")
