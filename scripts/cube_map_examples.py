#!/usr/bin/env python3
"""Сгенерировать автономные примеры для рендерера карты Куба.

Это единственный мост между production-моделью ``CubeSpec`` и намеренно
маленькой входной моделью рендерера. Модуль не читает БД и не запускает
Telegram/RCON-компоненты.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image


# Поддерживаем и прямой запуск, и предпочтительную форму ``python -m ...``.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from game.cube import (  # noqa: E402
    CubeSpec,
    RoomSpec,
    generate_cube,
    room_map_category,
)
from scripts.cube_map_renderer import (  # noqa: E402
    KnownRoom,
    MapSnapshot,
    render_map,
    render_map_png,
)


DEMO_SEED = 20260725
EXAMPLE_MILESTONES = (
    (1, "01_start.png"),
    (4, "02_first_steps.png"),
    (9, "03_branch_and_loop.png"),
    (16, "04_full_map.png"),
)
CONTACT_SHEET_NAME = "contact_sheet.png"
CONTACT_SHEET_BACKGROUND = (11, 15, 20)


def category_from_cube_room(room: RoomSpec) -> str:
    """Свести доменный тип комнаты к трёхцветной категории миникарты."""
    return room_map_category(room.kind, room.effect_kind)


def snapshot_from_spec(
    spec: CubeSpec,
    visited_room_ids: Iterable[int],
    current_room_id: int,
) -> MapSnapshot:
    """Адаптировать ``CubeSpec`` и личное множество посещений для рендерера.

    В снимок попадает каждый реальный проход посещённой комнаты. Поэтому к
    посещённому соседу рендерер проводит полный коридор, а к непосещённому —
    короткий выход в темноту. Эффекты комнат, включая vector/tunnel,
    намеренно игнорируются.
    """
    visited = frozenset(visited_room_ids)
    if not visited:
        raise ValueError("visited_room_ids не должен быть пустым")
    if current_room_id not in visited:
        raise ValueError("current_room_id должен входить в посещённые комнаты")

    known_rooms: list[KnownRoom] = []
    for room_id in sorted(visited):
        try:
            room = spec.room(room_id)
        except KeyError as error:
            raise ValueError(f"неизвестный room_id Куба: {room_id}") from error
        exits = frozenset(
            direction.value for direction, _target in spec.neighbors(room_id)
        )
        known_rooms.append(
            KnownRoom(
                room_id=room.room_id,
                row=room.row,
                column=room.column,
                exits=exits,
                category=category_from_cube_room(room),
            )
        )

    return MapSnapshot(
        size=spec.size,
        rooms=tuple(known_rooms),
        current_room_id=current_room_id,
    )


def depth_first_walk(
    spec: CubeSpec,
    start_room_id: int | None = None,
) -> tuple[int, ...]:
    """Вернуть детерминированный и геометрически допустимый DFS-маршрут.

    Обратные шаги остаются в результате: каждая соседняя пара маршрута связана
    реальным проходом, а первые открытия образуют растущее множество посещений.
    """
    start = spec.start_room_id if start_room_id is None else start_room_id
    try:
        spec.room(start)
    except KeyError as error:
        raise ValueError(f"неизвестная стартовая комната DFS: {start}") from error

    visited: set[int] = set()
    walk: list[int] = []

    def visit(room_id: int) -> None:
        visited.add(room_id)
        walk.append(room_id)
        for _direction, neighbour_id in spec.neighbors(room_id):
            if neighbour_id in visited:
                continue
            visit(neighbour_id)
            walk.append(room_id)

    visit(start)
    if len(visited) != len(spec.rooms):
        raise ValueError(
            "проходы Куба несвязны: "
            f"DFS достиг {len(visited)} из {len(spec.rooms)} комнат"
        )
    return tuple(walk)


def _milestone_snapshots(spec: CubeSpec) -> tuple[MapSnapshot, ...]:
    walk = depth_first_walk(spec)
    visited: set[int] = set()
    snapshots: list[MapSnapshot] = []
    milestone_index = 0

    for current_room_id in walk:
        visited.add(current_room_id)
        if milestone_index >= len(EXAMPLE_MILESTONES):
            break
        wanted_count, _filename = EXAMPLE_MILESTONES[milestone_index]
        if len(visited) == wanted_count:
            snapshots.append(
                snapshot_from_spec(spec, visited, current_room_id)
            )
            milestone_index += 1

    if milestone_index != len(EXAMPLE_MILESTONES):
        missing = [
            count for count, _filename in EXAMPLE_MILESTONES[milestone_index:]
        ]
        raise ValueError(f"DFS не достиг стадий примера: {missing}")
    return tuple(snapshots)


def _write_bytes_atomically(path: Path, payload: bytes) -> None:
    """Записать файл целиком и опубликовать его одним атомарным replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.replace(path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.convert("RGB").save(
        buffer,
        format="PNG",
        optimize=True,
    )
    return buffer.getvalue()


def _contact_sheet(images: Sequence[Image.Image]) -> Image.Image:
    if len(images) != 4:
        raise ValueError("для листа сравнения нужны ровно четыре изображения")
    tile_size = images[0].size
    if any(image.size != tile_size for image in images):
        raise ValueError("все изображения листа должны быть одного размера")

    tile_width, tile_height = tile_size
    sheet = Image.new(
        "RGB",
        (tile_width * 2, tile_height * 2),
        CONTACT_SHEET_BACKGROUND,
    )
    for index, image in enumerate(images):
        x = (index % 2) * tile_width
        y = (index // 2) * tile_height
        sheet.paste(image.convert("RGB"), (x, y))
    return sheet


def generate_examples(output_dir: Path) -> tuple[Path, ...]:
    """Создать четыре детерминированные карты и лист сравнения 2×2."""
    output_dir = Path(output_dir).expanduser()
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError(f"output path is not a directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    spec = generate_cube(DEMO_SEED)
    snapshots = _milestone_snapshots(spec)
    generated: list[Path] = []
    rendered_images: list[Image.Image] = []

    for snapshot, (_count, filename) in zip(
        snapshots,
        EXAMPLE_MILESTONES,
    ):
        output_path = output_dir / filename
        _write_bytes_atomically(output_path, render_map_png(snapshot))
        generated.append(output_path)
        rendered_images.append(render_map(snapshot))

    sheet = _contact_sheet(rendered_images)
    sheet_path = output_dir / CONTACT_SHEET_NAME
    _write_bytes_atomically(sheet_path, _png_bytes(sheet))
    generated.append(sheet_path)
    return tuple(generated)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Сгенерировать четыре стадии карты Куба и лист сравнения 2x2"
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="каталог для пяти демонстрационных PNG",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        generated = generate_examples(args.output_dir)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    print(f"Готово: {len(generated)} PNG в {Path(args.output_dir).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
