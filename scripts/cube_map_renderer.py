#!/usr/bin/env python3
"""Детерминированный Pillow-рендерер личной карты лабиринта Куба.

Модуль намеренно не знает о SQLite, aiogram и доменной модели Куба. Вызывающая
сторона передаёт уже отфильтрованный снимок только тех комнат, которые лично
посетил игрок, вместе со всеми физическими выходами из этих комнат.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import FrozenSet

from PIL import Image, ImageDraw


LOGICAL_SIZE = (256, 256)
OUTPUT_SIZE = (1024, 1024)
ROOM_SIZE = (36, 28)
GRID_STEP = (48, 44)

PASSAGE_THICKNESS = 6
UNKNOWN_STUB_LENGTH = 6
ROOM_OUTLINE_WIDTH = 2

BACKGROUND = (11, 15, 20)
PANEL_FILL = (18, 25, 34)
PANEL_OUTLINE_DARK = (5, 7, 9)
PANEL_OUTLINE_LIGHT = (42, 53, 65)
BACKGROUND_SPECK = (24, 33, 43)
PASSAGE_FILL = (138, 150, 163)
CURRENT_OUTLINE = (245, 252, 255)
PLAYER_MARKER = (255, 255, 255)
PLAYER_MARKER_OUTLINE = (22, 37, 46)

CATEGORY_DANGEROUS = "dangerous"
CATEGORY_NEUTRAL = "neutral"
CATEGORY_USEFUL = "useful"
ROOM_CATEGORIES = frozenset(
    {CATEGORY_DANGEROUS, CATEGORY_NEUTRAL, CATEGORY_USEFUL}
)

DANGEROUS_ROOM_FILL = (130, 49, 61)
DANGEROUS_ROOM_OUTLINE = (232, 117, 130)
NEUTRAL_ROOM_FILL = (58, 70, 82)
NEUTRAL_ROOM_OUTLINE = (167, 176, 186)
USEFUL_ROOM_FILL = (54, 108, 72)
USEFUL_ROOM_OUTLINE = (128, 205, 151)

# Старые имена оставлены как нейтральные aliases для простого переиспользования
# палитры и обратной совместимости автономного прототипа.
ROOM_FILL = NEUTRAL_ROOM_FILL
ROOM_OUTLINE = NEUTRAL_ROOM_OUTLINE

ROOM_STYLES = {
    CATEGORY_DANGEROUS: (
        DANGEROUS_ROOM_FILL,
        DANGEROUS_ROOM_OUTLINE,
        (75, 22, 29),
    ),
    CATEGORY_NEUTRAL: (
        NEUTRAL_ROOM_FILL,
        NEUTRAL_ROOM_OUTLINE,
        PANEL_OUTLINE_DARK,
    ),
    CATEGORY_USEFUL: (
        USEFUL_ROOM_FILL,
        USEFUL_ROOM_OUTLINE,
        (25, 61, 38),
    ),
}

DIRECTIONS = ("n", "e", "s", "w")
DIRECTION_DELTAS = {
    "n": (-1, 0),
    "e": (0, 1),
    "s": (1, 0),
    "w": (0, -1),
}
OPPOSITE_DIRECTIONS = {
    "n": "s",
    "e": "w",
    "s": "n",
    "w": "e",
}

Rect = tuple[int, int, int, int]


@dataclass(frozen=True)
class KnownRoom:
    """Одна лично посещённая комната и все реальные выходы из неё."""

    room_id: int
    row: int
    column: int
    exits: FrozenSet[str]
    category: str = CATEGORY_NEUTRAL

    def __post_init__(self) -> None:
        # Глубоко замораживаем вход: переданный вызывающим set не должен делать
        # снимок изменяемым после создания dataclass.
        object.__setattr__(self, "exits", frozenset(self.exits))


@dataclass(frozen=True)
class MapSnapshot:
    """Готовый к отрисовке личный снимок карты."""

    size: int
    rooms: tuple[KnownRoom, ...]
    current_room_id: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "rooms", tuple(self.rooms))


@dataclass(frozen=True)
class _MapLayout:
    """Вычисленная геометрия логического холста, удобная для узких тестов."""

    origin: tuple[int, int]
    room_rects: dict[int, Rect]
    corridor_rects: tuple[Rect, ...]
    stub_rects: tuple[Rect, ...]


def _validate_snapshot(snapshot: MapSnapshot) -> None:
    if not isinstance(snapshot, MapSnapshot):
        raise TypeError("snapshot must be a MapSnapshot")
    if not isinstance(snapshot.size, int) or isinstance(snapshot.size, bool):
        raise ValueError("map size must be an integer")
    if snapshot.size <= 0:
        raise ValueError("map size must be positive")
    if not snapshot.rooms:
        raise ValueError("map snapshot must contain at least one known room")

    room_ids: set[int] = set()
    coordinates: set[tuple[int, int]] = set()
    by_coordinate: dict[tuple[int, int], KnownRoom] = {}

    for room in snapshot.rooms:
        if not isinstance(room, KnownRoom):
            raise TypeError("snapshot rooms must be KnownRoom instances")
        if not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (room.room_id, room.row, room.column)
        ):
            raise ValueError("room id and coordinates must be integers")
        if room.room_id in room_ids:
            raise ValueError(f"duplicate room id: {room.room_id}")
        coordinate = (room.row, room.column)
        if coordinate in coordinates:
            raise ValueError(f"duplicate room coordinates: {coordinate}")
        if not (0 <= room.row < snapshot.size and 0 <= room.column < snapshot.size):
            raise ValueError(
                f"room {room.room_id} is outside the {snapshot.size}x{snapshot.size} map"
            )
        invalid_directions = set(room.exits) - set(DIRECTIONS)
        if invalid_directions:
            raise ValueError(
                f"room {room.room_id} has invalid exits: {sorted(invalid_directions)}"
            )
        if room.category not in ROOM_CATEGORIES:
            raise ValueError(
                f"room {room.room_id} has invalid category: {room.category!r}"
            )

        room_ids.add(room.room_id)
        coordinates.add(coordinate)
        by_coordinate[coordinate] = room

    if snapshot.current_room_id not in room_ids:
        raise ValueError("current room must be present among known rooms")

    for room in snapshot.rooms:
        for direction in room.exits:
            delta_row, delta_column = DIRECTION_DELTAS[direction]
            target_coordinate = (
                room.row + delta_row,
                room.column + delta_column,
            )
            if not (
                0 <= target_coordinate[0] < snapshot.size
                and 0 <= target_coordinate[1] < snapshot.size
            ):
                raise ValueError(
                    f"room {room.room_id} exit {direction!r} leaves the map"
                )
            target = by_coordinate.get(target_coordinate)
            if target is not None and OPPOSITE_DIRECTIONS[direction] not in target.exits:
                raise ValueError(
                    "known passage must be declared by both rooms: "
                    f"{room.room_id} {direction} -> {target.room_id}"
                )


def _centered_rect(
    center_x: int,
    center_y: int,
    width: int,
    height: int,
) -> Rect:
    left = center_x - width // 2
    top = center_y - height // 2
    return left, top, left + width - 1, top + height - 1


def _passage_rect(
    source_center: tuple[int, int],
    target_center: tuple[int, int],
) -> Rect:
    source_x, source_y = source_center
    target_x, target_y = target_center
    half = PASSAGE_THICKNESS // 2
    if source_y == target_y:
        return (
            min(source_x, target_x),
            source_y - half,
            max(source_x, target_x),
            source_y + PASSAGE_THICKNESS - half - 1,
        )
    return (
        source_x - half,
        min(source_y, target_y),
        source_x + PASSAGE_THICKNESS - half - 1,
        max(source_y, target_y),
    )


def _stub_rect(room_rect: Rect, direction: str) -> Rect:
    left, top, right, bottom = room_rect
    center_x = (left + right + 1) // 2
    center_y = (top + bottom + 1) // 2
    half = PASSAGE_THICKNESS // 2
    if direction == "n":
        return (
            center_x - half,
            top - UNKNOWN_STUB_LENGTH,
            center_x + PASSAGE_THICKNESS - half - 1,
            top + 1,
        )
    if direction == "e":
        return (
            right - 1,
            center_y - half,
            right + UNKNOWN_STUB_LENGTH,
            center_y + PASSAGE_THICKNESS - half - 1,
        )
    if direction == "s":
        return (
            center_x - half,
            bottom - 1,
            center_x + PASSAGE_THICKNESS - half - 1,
            bottom + UNKNOWN_STUB_LENGTH,
        )
    return (
        left - UNKNOWN_STUB_LENGTH,
        center_y - half,
        left + 1,
        center_y + PASSAGE_THICKNESS - half - 1,
    )


def _layout_snapshot(snapshot: MapSnapshot) -> _MapLayout:
    """Проверить снимок и вычислить геометрию без рисования."""
    _validate_snapshot(snapshot)

    min_row = min(room.row for room in snapshot.rooms)
    max_row = max(room.row for room in snapshot.rooms)
    min_column = min(room.column for room in snapshot.rooms)
    max_column = max(room.column for room in snapshot.rooms)

    room_width, room_height = ROOM_SIZE
    step_x, step_y = GRID_STEP
    group_width = (max_column - min_column) * step_x + room_width
    group_height = (max_row - min_row) * step_y + room_height
    group_left = (LOGICAL_SIZE[0] - group_width) // 2
    group_top = (LOGICAL_SIZE[1] - group_height) // 2
    origin = (
        group_left + room_width // 2,
        group_top + room_height // 2,
    )

    room_rects: dict[int, Rect] = {}
    centers: dict[int, tuple[int, int]] = {}
    by_coordinate = {(room.row, room.column): room for room in snapshot.rooms}
    for room in snapshot.rooms:
        center = (
            origin[0] + (room.column - min_column) * step_x,
            origin[1] + (room.row - min_row) * step_y,
        )
        centers[room.room_id] = center
        room_rects[room.room_id] = _centered_rect(
            center[0], center[1], room_width, room_height
        )

    corridor_rects: list[Rect] = []
    stub_rects: list[Rect] = []
    rendered_edges: set[tuple[int, int]] = set()
    ordered_rooms = sorted(
        snapshot.rooms,
        key=lambda room: (room.row, room.column, room.room_id),
    )
    for room in ordered_rooms:
        for direction in DIRECTIONS:
            if direction not in room.exits:
                continue
            delta_row, delta_column = DIRECTION_DELTAS[direction]
            target = by_coordinate.get(
                (room.row + delta_row, room.column + delta_column)
            )
            if target is None:
                stub_rects.append(_stub_rect(room_rects[room.room_id], direction))
                continue
            edge = tuple(sorted((room.room_id, target.room_id)))
            if edge in rendered_edges:
                continue
            rendered_edges.add(edge)
            corridor_rects.append(
                _passage_rect(centers[room.room_id], centers[target.room_id])
            )

    return _MapLayout(
        origin=origin,
        room_rects=room_rects,
        corridor_rects=tuple(corridor_rects),
        stub_rects=tuple(stub_rects),
    )


def _inset(rect: Rect, amount: int) -> Rect:
    return (
        rect[0] + amount,
        rect[1] + amount,
        rect[2] - amount,
        rect[3] - amount,
    )


def _draw_background(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((8, 8, 247, 247), fill=PANEL_OUTLINE_DARK)
    draw.rectangle((10, 10, 245, 245), fill=PANEL_OUTLINE_LIGHT)
    draw.rectangle((12, 12, 243, 243), fill=PANEL_FILL)

    # Нерегулярная, но полностью детерминированная крапинка не требует
    # текстурного ассета и не меняет результат между запусками.
    for y in range(17, 240, 11):
        for x in range(17, 240, 13):
            if (x * 17 + y * 31) % 7 == 0:
                draw.point((x, y), fill=BACKGROUND_SPECK)


def _draw_room(
    draw: ImageDraw.ImageDraw,
    rect: Rect,
    *,
    category: str,
    current: bool,
) -> None:
    fill, category_outline, shadow = ROOM_STYLES[category]
    outline = CURRENT_OUTLINE if current else category_outline
    draw.rectangle(rect, fill=outline)
    draw.rectangle(_inset(rect, ROOM_OUTLINE_WIDTH), fill=fill)

    # Один пиксель внутренней тени сохраняет ощущение металлической панели.
    inner = _inset(rect, ROOM_OUTLINE_WIDTH)
    draw.line(
        (inner[0], inner[3], inner[2], inner[3]),
        fill=shadow,
    )

    if not current:
        return
    center_x = (rect[0] + rect[2] + 1) // 2
    center_y = (rect[1] + rect[3] + 1) // 2
    draw.polygon(
        (
            (center_x, center_y - 5),
            (center_x + 5, center_y),
            (center_x, center_y + 5),
            (center_x - 5, center_y),
        ),
        fill=PLAYER_MARKER_OUTLINE,
    )
    draw.polygon(
        (
            (center_x, center_y - 3),
            (center_x + 3, center_y),
            (center_x, center_y + 3),
            (center_x - 3, center_y),
        ),
        fill=PLAYER_MARKER,
    )


def render_map(snapshot: MapSnapshot) -> Image.Image:
    """Вернуть новую карту 1024×1024; входной снимок остаётся неизменным."""
    layout = _layout_snapshot(snapshot)
    logical = Image.new("RGB", LOGICAL_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(logical)
    _draw_background(draw)

    for rect in layout.corridor_rects:
        draw.rectangle(rect, fill=PASSAGE_FILL)
    for rect in layout.stub_rects:
        draw.rectangle(rect, fill=PASSAGE_FILL)
    for room in sorted(
        snapshot.rooms,
        key=lambda item: (item.row, item.column, item.room_id),
    ):
        _draw_room(
            draw,
            layout.room_rects[room.room_id],
            category=room.category,
            current=room.room_id == snapshot.current_room_id,
        )

    return logical.resize(OUTPUT_SIZE, resample=Image.Resampling.NEAREST)


def render_map_png(snapshot: MapSnapshot) -> bytes:
    """Закодировать карту в детерминированный Telegram-ready RGB PNG."""
    image = render_map(snapshot)
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


__all__ = [
    "CATEGORY_DANGEROUS",
    "CATEGORY_NEUTRAL",
    "CATEGORY_USEFUL",
    "KnownRoom",
    "MapSnapshot",
    "render_map",
    "render_map_png",
]
