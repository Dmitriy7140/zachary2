"""Доменная модель и детерминированный генератор мини-игры «Куб»."""
from __future__ import annotations

import asyncio
import logging
import random
import secrets
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Iterable, TYPE_CHECKING

from game.items import ITEMS

if TYPE_CHECKING:
    from aiogram import Bot


log = logging.getLogger(__name__)

GRID_SIZE = 4
ROOM_COUNT = GRID_SIZE * GRID_SIZE
LAYOUT_VERSION = 1
SCHEDULER_INTERVAL_SECONDS = 30
NOTIFICATION_RETRY_BASE_SECONDS = 30
NOTIFICATION_RETRY_MAX_SECONDS = 60 * 60
NOTIFICATION_BATCH_SIZE = 20
WORK_CLAIM_LEASE_SECONDS = 5 * 60

PRIVATE_NOTIFICATION = "lobby_private"
PUBLIC_NOTIFICATION = "winner_public"

ROOM_START = "start"
ROOM_PRIZE = "prize"
ROOM_NEUTRAL = "neutral"
ROOM_HAZARD = "hazard"
ROOM_ANOMALY = "anomaly"

EFFECT_ARCHIVE = "archive"
EFFECT_ECHO = "echo"
EFFECT_DARK = "dark"
EFFECT_VECTOR = "vector"
EFFECT_TUNNEL = "tunnel"
TRANSFER_EFFECTS = frozenset({EFFECT_VECTOR, EFFECT_TUNNEL})


class Direction(str, Enum):
    NORTH = "n"
    EAST = "e"
    SOUTH = "s"
    WEST = "w"


DIRECTIONS = (
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
)
_DIRECTION_DELTAS = {
    Direction.NORTH: (-1, 0),
    Direction.EAST: (0, 1),
    Direction.SOUTH: (1, 0),
    Direction.WEST: (0, -1),
}
_OPPOSITE_DIRECTIONS = {
    Direction.NORTH: Direction.SOUTH,
    Direction.EAST: Direction.WEST,
    Direction.SOUTH: Direction.NORTH,
    Direction.WEST: Direction.EAST,
}


@dataclass(frozen=True)
class HazardSpec:
    kind: str
    item_key: str
    consume_qty: int


HAZARD_SPECS = (
    HazardSpec("flooded_floor", "bucket", 0),
    HazardSpec("chasm_lever", "rod", 0),
    HazardSpec("mutant_leeches", "bait_1", 1),
    HazardSpec("wire_net", "znak", 0),
    HazardSpec("locked_hatch", "lockpicks", 0),
    HazardSpec("shark_guard", "bait_3", 1),
    HazardSpec("laser_grid", "milk_can", 1),
    HazardSpec("invisible_cutters", "egg", 1),
)
HAZARD_BY_KIND = {hazard.kind: hazard for hazard in HAZARD_SPECS}
ITEM_CONSUMPTION = {hazard.item_key: hazard.consume_qty for hazard in HAZARD_SPECS}


def _validate_hazard_registry() -> None:
    expected = {
        "bucket": 0,
        "rod": 0,
        "znak": 0,
        "lockpicks": 0,
        "bait_1": 1,
        "bait_3": 1,
        "milk_can": 1,
        "egg": 1,
    }
    if ITEM_CONSUMPTION != expected:
        raise RuntimeError("Cube item whitelist no longer matches its v1 contract")
    missing = set(expected) - set(ITEMS)
    if missing:
        raise RuntimeError(f"Cube references unknown ITEMS keys: {sorted(missing)}")
    if len(HAZARD_BY_KIND) != len(HAZARD_SPECS):
        raise RuntimeError("Cube hazard kinds must be unique")


_validate_hazard_registry()


@dataclass(frozen=True)
class RoomSpec:
    room_id: int
    row: int
    column: int
    code: int
    kind: str
    description_key: str
    hazard_kind: str | None = None
    required_item_key: str | None = None
    consume_qty: int = 0
    is_required: bool = False
    effect_kind: str | None = None
    effect_target_room_id: int | None = None
    effect_arg: str | None = None


@dataclass(frozen=True)
class PassageSpec:
    room_a: int
    room_b: int
    is_extra: bool = False

    def __post_init__(self) -> None:
        if self.room_a >= self.room_b:
            raise ValueError("passage rooms must be stored as room_a < room_b")


@dataclass(frozen=True)
class CubeSpec:
    size: int
    seed: int
    layout_version: int
    start_room_id: int
    prize_room_id: int
    mandatory_room_id: int
    rooms: tuple[RoomSpec, ...]
    passages: tuple[PassageSpec, ...]

    def room(self, room_id: int) -> RoomSpec:
        if 0 <= room_id < len(self.rooms):
            room = self.rooms[room_id]
            if room.room_id == room_id:
                return room
        for room in self.rooms:
            if room.room_id == room_id:
                return room
        raise KeyError(room_id)

    def has_passage(self, room_a: int, room_b: int) -> bool:
        edge = _edge(room_a, room_b)
        return any((passage.room_a, passage.room_b) == edge for passage in self.passages)

    def neighbor(self, room_id: int, direction: Direction | str) -> int | None:
        target = grid_neighbor(room_id, direction, self.size)
        if target is None or not self.has_passage(room_id, target):
            return None
        return target

    def neighbors(self, room_id: int) -> tuple[tuple[Direction, int], ...]:
        return tuple(
            (direction, target)
            for direction in DIRECTIONS
            if (target := self.neighbor(room_id, direction)) is not None
        )


@dataclass(frozen=True)
class _GeneratedLayout:
    start: int
    prize: int
    mandatory: int
    tree_edges: frozenset[tuple[int, int]]
    extra_edges: frozenset[tuple[int, int]]
    tree_path: tuple[int, ...]
    components_without_mandatory: tuple[frozenset[int], ...]
    hazards: dict[int, HazardSpec]
    effects: dict[int, tuple[str, int | None, str | None]]


def opposite_direction(direction: Direction | str) -> Direction:
    return _OPPOSITE_DIRECTIONS[Direction(direction)]


def grid_neighbor(
    room_id: int,
    direction: Direction | str,
    size: int = GRID_SIZE,
) -> int | None:
    if not 0 <= room_id < size * size:
        return None
    row, column = divmod(room_id, size)
    delta_row, delta_column = _DIRECTION_DELTAS[Direction(direction)]
    target_row = row + delta_row
    target_column = column + delta_column
    if not (0 <= target_row < size and 0 <= target_column < size):
        return None
    return target_row * size + target_column


def direction_between(
    room_a: int,
    room_b: int,
    size: int = GRID_SIZE,
) -> Direction:
    for direction in DIRECTIONS:
        if grid_neighbor(room_a, direction, size) == room_b:
            return direction
    raise ValueError(f"rooms {room_a} and {room_b} are not grid neighbors")


def generate_cube(seed: int, *, layout_version: int = LAYOUT_VERSION) -> CubeSpec:
    """Построить неизменяемую спецификацию Куба из сохранённого seed.

    Внутренние попытки тоже детерминированы. Seed описывает всё поколение,
    поэтому вызывающий код обязан сохранить итоговые комнаты и двери в БД.
    """
    if layout_version != LAYOUT_VERSION:
        raise ValueError(f"unsupported Cube layout version: {layout_version}")

    source = random.Random(seed)
    layout: _GeneratedLayout | None = None
    for _ in range(2048):
        attempt = random.Random(source.getrandbits(128))
        layout = _try_generate_layout(attempt)
        if layout is not None:
            break
    if layout is None:
        raise RuntimeError("failed to generate a valid Cube layout")

    rng = random.Random(source.getrandbits(128))
    codes = rng.sample(range(100, 1000), ROOM_COUNT)
    neutral_keys = [
        "neutral.white",
        "neutral.amber",
        "neutral.blue",
        "neutral.green",
        "neutral.red",
        "neutral.violet",
        "neutral.rust",
        "neutral.mirror",
    ]
    rng.shuffle(neutral_keys)

    rooms: list[RoomSpec] = []
    for room_id in range(ROOM_COUNT):
        row, column = divmod(room_id, GRID_SIZE)
        hazard = layout.hazards.get(room_id)
        effect = layout.effects.get(room_id)
        if room_id == layout.start:
            kind = ROOM_START
            description_key = "start"
        elif room_id == layout.prize:
            kind = ROOM_PRIZE
            description_key = "prize"
        elif hazard is not None:
            kind = ROOM_HAZARD
            description_key = f"hazard.{hazard.kind}"
        elif effect is not None:
            kind = ROOM_ANOMALY
            description_key = f"anomaly.{effect[0]}"
        else:
            kind = ROOM_NEUTRAL
            description_key = neutral_keys[room_id % len(neutral_keys)]

        rooms.append(
            RoomSpec(
                room_id=room_id,
                row=row,
                column=column,
                code=codes[room_id],
                kind=kind,
                description_key=description_key,
                hazard_kind=hazard.kind if hazard else None,
                required_item_key=hazard.item_key if hazard else None,
                consume_qty=hazard.consume_qty if hazard else 0,
                is_required=room_id == layout.mandatory,
                effect_kind=effect[0] if effect else None,
                effect_target_room_id=effect[1] if effect else None,
                effect_arg=(
                    str(codes[effect[1]])
                    if effect is not None
                    and effect[0] in TRANSFER_EFFECTS
                    and effect[1] is not None
                    else effect[2] if effect else None
                ),
            )
        )

    passages = tuple(
        PassageSpec(room_a=a, room_b=b, is_extra=edge in layout.extra_edges)
        for edge in sorted(layout.tree_edges | layout.extra_edges)
        for a, b in (edge,)
    )
    result = CubeSpec(
        size=GRID_SIZE,
        seed=seed,
        layout_version=layout_version,
        start_room_id=layout.start,
        prize_room_id=layout.prize,
        mandatory_room_id=layout.mandatory,
        rooms=tuple(rooms),
        passages=passages,
    )
    _validate_cube(result)
    return result


def new_cube_spec(
    *,
    randbits: Callable[[int], int] = secrets.randbits,
) -> CubeSpec:
    """Создать новую production-спецификацию с сохраняемым 63-bit seed."""
    return generate_cube(randbits(63))


def _try_generate_layout(rng: random.Random) -> _GeneratedLayout | None:
    grid_edges = _all_grid_edges()
    shuffled_edges = list(grid_edges)
    rng.shuffle(shuffled_edges)
    tree_edges = _spanning_tree(shuffled_edges)
    tree_adjacency = _adjacency(tree_edges)

    diameter, diameter_paths = _diameter_paths(tree_adjacency)
    if diameter < 6:
        return None
    path = list(rng.choice(diameter_paths))
    if rng.randrange(2):
        path.reverse()
    start, prize = path[0], path[-1]

    mandatory_candidates = []
    for index in range(3, len(path) - 3):
        mandatory = path[index]
        components = _components_without(tree_edges, mandatory)
        start_component = _component_containing(components, start)
        prize_component = _component_containing(components, prize)
        if len(start_component) >= 3 and len(prize_component) >= 3:
            mandatory_candidates.append((mandatory, components))
    if not mandatory_candidates:
        return None
    mandatory, components = rng.choice(mandatory_candidates)
    component_index = {
        room_id: index
        for index, component in enumerate(components)
        for room_id in component
    }

    extra_candidates = [
        edge
        for edge in grid_edges - tree_edges
        if mandatory not in edge
        and component_index[edge[0]] == component_index[edge[1]]
    ]
    rng.shuffle(extra_candidates)
    wanted_extra = rng.randint(2, 4)
    extra_edges: set[tuple[int, int]] = set()
    for edge in extra_candidates:
        candidate_edges = tree_edges | extra_edges | {edge}
        if _shortest_distance(candidate_edges, start, prize) >= 6:
            extra_edges.add(edge)
            if len(extra_edges) == wanted_extra:
                break
    if len(extra_edges) < 2:
        return None

    optional_candidates = sorted(set(range(ROOM_COUNT)) - set(path))
    optional_count = rng.randint(0, min(2, len(optional_candidates)))
    optional_rooms = rng.sample(optional_candidates, optional_count)
    selected_hazards = rng.sample(HAZARD_SPECS, 1 + optional_count)
    hazards = {mandatory: selected_hazards[0]}
    hazards.update(zip(optional_rooms, selected_hazards[1:]))

    effects = _assign_effects(
        rng,
        tree_edges | extra_edges,
        components,
        start,
        prize,
        set(hazards),
    )
    if effects is None:
        return None
    if not _prize_reachable(
        tree_edges | extra_edges,
        effects,
        start,
        prize,
        blocked=set(optional_rooms),
    ):
        return None

    return _GeneratedLayout(
        start=start,
        prize=prize,
        mandatory=mandatory,
        tree_edges=frozenset(tree_edges),
        extra_edges=frozenset(extra_edges),
        tree_path=tuple(path),
        components_without_mandatory=tuple(frozenset(c) for c in components),
        hazards=hazards,
        effects=effects,
    )


def _assign_effects(
    rng: random.Random,
    passages: set[tuple[int, int]],
    components: list[set[int]],
    start: int,
    prize: int,
    hazards: set[int],
) -> dict[int, tuple[str, int | None, str | None]] | None:
    eligible = set(range(ROOM_COUNT)) - hazards - {start, prize}
    if len(eligible) < 6:
        return None
    component_index = {
        room_id: index
        for index, component in enumerate(components)
        for room_id in component
    }

    pair_components = [
        sorted(eligible & component)
        for component in components
        if len(eligible & component) >= 2
    ]
    if not pair_components:
        return None
    tunnel_pool = rng.choice(pair_components)
    tunnel_a, tunnel_b = rng.sample(tunnel_pool, 2)
    effects: dict[int, tuple[str, int | None, str | None]] = {
        tunnel_a: (EFFECT_TUNNEL, tunnel_b, None),
        tunnel_b: (EFFECT_TUNNEL, tunnel_a, None),
    }

    remaining = eligible - {tunnel_a, tunnel_b}
    vector_sources = [
        room_id
        for room_id in remaining
        if any(
            target != room_id
            and target not in hazards
            and target != prize
            and component_index.get(target) == component_index.get(room_id)
            for target in range(ROOM_COUNT)
        )
    ]
    if not vector_sources:
        return None
    vector_source = rng.choice(vector_sources)
    vector_targets = [
        target
        for target in range(ROOM_COUNT)
        if target != vector_source
        and target not in hazards
        and target not in {prize, start}
        and component_index.get(target) == component_index.get(vector_source)
    ]
    if not vector_targets:
        return None
    vector_target = rng.choice(vector_targets)
    effects[vector_source] = (EFFECT_VECTOR, vector_target, str(vector_target))

    remaining.remove(vector_source)
    if len(remaining) < 3:
        return None
    archive, echo, dark = rng.sample(sorted(remaining), 3)
    archive_neighbors = sorted(_adjacency(passages)[archive])
    archive_target = rng.choice(archive_neighbors) if archive_neighbors else None
    archive_direction = (
        direction_between(archive, archive_target).value
        if archive_target is not None
        else None
    )
    effects[archive] = (EFFECT_ARCHIVE, archive_target, archive_direction)
    effects[echo] = (EFFECT_ECHO, None, None)
    effects[dark] = (EFFECT_DARK, None, None)
    return effects


def _prize_reachable(
    passages: set[tuple[int, int]],
    effects: dict[int, tuple[str, int | None, str | None]],
    start: int,
    prize: int,
    *,
    blocked: set[int],
) -> bool:
    adjacency = _adjacency(passages)
    seen = {start}
    queue = deque([start])
    while queue:
        source = queue.popleft()
        for entered in adjacency[source]:
            if entered in blocked:
                continue
            if entered == prize:
                return True
            effect_kind, target, _ = effects.get(entered, (None, None, None))
            final = target if effect_kind in TRANSFER_EFFECTS else entered
            if final is None or final in blocked or final in seen:
                continue
            seen.add(final)
            queue.append(final)
    return False


def _validate_cube(spec: CubeSpec) -> None:
    if spec.size != GRID_SIZE or len(spec.rooms) != ROOM_COUNT:
        raise AssertionError("Cube must contain exactly 16 rooms")
    if {room.room_id for room in spec.rooms} != set(range(ROOM_COUNT)):
        raise AssertionError("Cube room ids must be contiguous")
    if len({room.code for room in spec.rooms}) != ROOM_COUNT:
        raise AssertionError("Cube room codes must be unique")
    required = [room for room in spec.rooms if room.is_required]
    if len(required) != 1 or required[0].room_id != spec.mandatory_room_id:
        raise AssertionError("Cube must contain one mandatory hazard")
    if required[0].kind != ROOM_HAZARD:
        raise AssertionError("mandatory room must be a hazard")
    for room in spec.rooms:
        if room.hazard_kind is None:
            continue
        hazard = HAZARD_BY_KIND.get(room.hazard_kind)
        if hazard is None:
            raise AssertionError("unknown Cube hazard")
        if room.required_item_key != hazard.item_key:
            raise AssertionError("hazard item mismatch")
        if room.consume_qty != hazard.consume_qty:
            raise AssertionError("hazard consumption mismatch")
    if _shortest_distance(_passage_edges(spec.passages), spec.start_room_id, spec.prize_room_id) < 6:
        raise AssertionError("start and prize are too close")


def _all_grid_edges(size: int = GRID_SIZE) -> set[tuple[int, int]]:
    edges = set()
    for room_id in range(size * size):
        for direction in (Direction.EAST, Direction.SOUTH):
            target = grid_neighbor(room_id, direction, size)
            if target is not None:
                edges.add(_edge(room_id, target))
    return edges


def _spanning_tree(edges: Iterable[tuple[int, int]]) -> set[tuple[int, int]]:
    parent = list(range(ROOM_COUNT))

    def find(room_id: int) -> int:
        while parent[room_id] != room_id:
            parent[room_id] = parent[parent[room_id]]
            room_id = parent[room_id]
        return room_id

    result = set()
    for room_a, room_b in edges:
        root_a, root_b = find(room_a), find(room_b)
        if root_a == root_b:
            continue
        parent[root_b] = root_a
        result.add(_edge(room_a, room_b))
        if len(result) == ROOM_COUNT - 1:
            return result
    raise AssertionError("grid edges did not produce a spanning tree")


def _diameter_paths(
    adjacency: dict[int, set[int]],
) -> tuple[int, list[tuple[int, ...]]]:
    maximum = -1
    paths = []
    for start in range(ROOM_COUNT):
        for finish in range(start + 1, ROOM_COUNT):
            path = _shortest_path(adjacency, start, finish)
            distance = len(path) - 1
            if distance > maximum:
                maximum = distance
                paths = [tuple(path)]
            elif distance == maximum:
                paths.append(tuple(path))
    return maximum, paths


def _shortest_path(
    adjacency: dict[int, set[int]],
    start: int,
    finish: int,
) -> list[int]:
    previous: dict[int, int | None] = {start: None}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        if current == finish:
            break
        for target in sorted(adjacency[current]):
            if target not in previous:
                previous[target] = current
                queue.append(target)
    if finish not in previous:
        return []
    path = []
    current: int | None = finish
    while current is not None:
        path.append(current)
        current = previous[current]
    path.reverse()
    return path


def _shortest_distance(
    edges: Iterable[tuple[int, int]],
    start: int,
    finish: int,
) -> int:
    path = _shortest_path(_adjacency(edges), start, finish)
    return len(path) - 1 if path else ROOM_COUNT + 1


def _components_without(
    edges: Iterable[tuple[int, int]],
    blocked: int,
) -> list[set[int]]:
    adjacency = _adjacency(edges)
    remaining = set(range(ROOM_COUNT)) - {blocked}
    components = []
    while remaining:
        first = min(remaining)
        component = {first}
        queue = deque([first])
        remaining.remove(first)
        while queue:
            current = queue.popleft()
            for target in adjacency[current]:
                if target == blocked or target not in remaining:
                    continue
                remaining.remove(target)
                component.add(target)
                queue.append(target)
        components.append(component)
    return components


def _component_containing(components: Iterable[set[int]], room_id: int) -> set[int]:
    for component in components:
        if room_id in component:
            return component
    raise AssertionError(f"room {room_id} has no component")


def _adjacency(
    edges: Iterable[tuple[int, int]],
) -> dict[int, set[int]]:
    result = {room_id: set() for room_id in range(ROOM_COUNT)}
    for room_a, room_b in edges:
        result[room_a].add(room_b)
        result[room_b].add(room_a)
    return result


def _edge(room_a: int, room_b: int) -> tuple[int, int]:
    return (room_a, room_b) if room_a < room_b else (room_b, room_a)


def _passage_edges(passages: Iterable[PassageSpec]) -> set[tuple[int, int]]:
    return {(passage.room_a, passage.room_b) for passage in passages}


# Lifecycle/orchestration functions are intentionally below the pure domain.
# Imports remain lazy to keep the generator usable in stdlib-only tests.


async def bootstrap_cube(now: datetime | None = None):
    """Обеспечить наличие текущего поколения перед началом polling."""
    from db import storage

    spec = new_cube_spec()
    if now is None:
        return await storage.bootstrap_cube(spec)
    return await storage.bootstrap_cube(spec, clock=lambda: now)


async def advance_cube_lifecycle(now: datetime | None = None):
    """Закрыть due-фазы и при необходимости создать новое поколение."""
    from db import storage

    spec = new_cube_spec()
    if now is None:
        return await storage.advance_cube_lifecycle(spec)
    return await storage.advance_cube_lifecycle(spec, clock=lambda: now)


async def run_cube_scheduler(bot: Bot) -> None:
    """Сразу обработать Cube lifecycle/outbox, затем повторять каждые 30 с."""
    try:
        while True:
            try:
                await _tick(bot)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("Куб: ошибка планировщика: %s", exc)
            await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        log.info("Планировщик Куба остановлен")
        raise


async def _tick(bot: Bot, *, now: datetime | None = None) -> None:
    """Один тестируемый такт lifecycle, Густава и Telegram-outbox."""
    try:
        if now is None:
            # Production-clock снимает сам storage уже под writer-lock.
            await advance_cube_lifecycle()
            current = datetime.utcnow()
        else:
            current = now
            await advance_cube_lifecycle(current)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.exception("Куб: не удалось продвинуть lifecycle: %s", exc)
        current = now or datetime.utcnow()

    await _process_pending_tax(
        bot,
        current,
        work_clock=(lambda: current) if now is not None else None,
    )
    await _deliver_pending_notifications(
        bot,
        current,
        send_clock=(lambda: current) if now is not None else None,
    )


async def _process_pending_tax(
    bot: Bot,
    current: datetime,
    *,
    work_clock: Callable[[], datetime] | None = None,
) -> None:
    from db import storage
    from game.taxman import maybe_gustav

    claim_token = secrets.token_urlsafe(16)
    now_iso = current.isoformat()
    claim_until = (
        current + timedelta(seconds=WORK_CLAIM_LEASE_SECONDS)
    ).isoformat()
    try:
        winners = await storage.claim_pending_cube_tax(
            claim_token,
            now_iso,
            claim_until,
            limit=NOTIFICATION_BATCH_SIZE,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.exception("Куб: не удалось арендовать проверки Густава: %s", exc)
        return

    for winner in winners:
        work_now = work_clock() if work_clock is not None else datetime.utcnow()
        try:
            claim_is_current = await storage.cube_tax_claim_is_current(
                winner.generation_id,
                claim_token,
                work_now.isoformat(),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception(
                "Куб #%s: не удалось перепроверить lease Густава: %s",
                winner.generation_id,
                exc,
            )
            continue
        if not claim_is_current:
            continue
        try:
            await maybe_gustav(
                bot,
                winner.winner_tg_id,
                winner.winner_balance_before,
                winner.winner_balance_after,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception(
                "Куб #%s: не удалось обработать Густава: %s",
                winner.generation_id,
                exc,
            )
            try:
                await storage.release_cube_tax_claim(
                    winner.generation_id, claim_token
                )
            except Exception as release_exc:
                log.exception(
                    "Куб #%s: не удалось освободить lease Густава: %s",
                    winner.generation_id,
                    release_exc,
                )
            continue

        try:
            marked = await storage.mark_cube_tax_processed(
                winner.generation_id, claim_token, work_now.isoformat()
            )
            if not marked:
                log.warning(
                    "Куб #%s: lease Густава потерян до отметки результата",
                    winner.generation_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Side effect мог пройти; lease оставляем до expiry, чтобы не
            # создавать мгновенный повтор после неоднозначного результата.
            log.exception(
                "Куб #%s: не удалось отметить проверку Густава: %s",
                winner.generation_id,
                exc,
            )


async def _deliver_pending_notifications(
    bot: Bot,
    current: datetime,
    *,
    send_clock: Callable[[], datetime] | None = None,
) -> None:
    from db import storage

    claim_token = secrets.token_urlsafe(16)
    now_iso = current.isoformat()
    claim_until = (
        current + timedelta(seconds=WORK_CLAIM_LEASE_SECONDS)
    ).isoformat()
    try:
        notifications = await storage.claim_cube_notifications(
            claim_token,
            now_iso,
            claim_until,
            limit=NOTIFICATION_BATCH_SIZE,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.exception("Куб: не удалось арендовать outbox: %s", exc)
        return

    for notification in notifications:
        try:
            sent = await _send_notification(
                bot,
                notification,
                now=send_clock() if send_clock is not None else None,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            delay = _notification_retry_delay(notification.attempts)
            next_attempt = (current + timedelta(seconds=delay)).isoformat()
            error = f"{type(exc).__name__}: {exc}"[:1000]
            log.exception(
                "Куб #%s: уведомление %s не доставлено "
                "(повтор через %s с): %s",
                notification.generation_id,
                notification.notification_id,
                delay,
                exc,
            )
            try:
                await storage.mark_cube_notification_retry(
                    notification.notification_id,
                    claim_token,
                    next_attempt,
                    error,
                )
            except asyncio.CancelledError:
                raise
            except Exception as retry_exc:
                log.exception(
                    "Куб: не удалось сохранить retry уведомления %s: %s",
                    notification.notification_id,
                    retry_exc,
                )
            continue

        try:
            if sent:
                marked = await storage.mark_cube_notification_sent(
                    notification.notification_id, claim_token, now_iso
                )
            else:
                marked = await storage.mark_cube_notification_stale(
                    notification.notification_id, claim_token
                )
            if not marked:
                log.warning(
                    "Куб: lease уведомления %s потерян до отметки результата",
                    notification.notification_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception(
                "Куб: не удалось отметить уведомление %s: %s",
                notification.notification_id,
                exc,
            )


async def _send_notification(
    bot: Bot,
    notification,
    *,
    now: datetime | None = None,
) -> bool:
    """Отправить запись outbox; False означает устаревший private invite."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from aiogram.utils.markdown import hlink

    from config import config
    from content import cube as cube_content
    from db import storage

    current = now or datetime.utcnow()
    claim_token = getattr(notification, "claim_token", None)
    if not await storage.cube_notification_claim_is_current(
        notification.notification_id,
        claim_token or "",
        current.isoformat(),
    ):
        return False

    if notification.kind == PRIVATE_NOTIFICATION:
        recipient = notification.recipient_tg_id
        if recipient is None:
            raise ValueError("у приглашения в Куб нет получателя")
        view = await storage.get_cube_view(recipient, notification.generation_id)
        entry_deadline = None
        if view is not None and view.generation_status == "waiting":
            entry_deadline = view.idle_expires_at
        elif view is not None and view.generation_status == "lobby":
            entry_deadline = view.lobby_closes_at
        if (
            view is None
            or view.generation_status not in ("waiting", "lobby")
            or view.participant_count >= view.max_participants
            or view.subscription_id != notification.subscription_id
            or entry_deadline is None
            or datetime.fromisoformat(entry_deadline) <= current
            or (
                view.closes_at is not None
                and datetime.fromisoformat(view.closes_at) <= current
            )
        ):
            return False
        token = secrets.token_urlsafe(8)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=f"🚪 Войти — {view.entry_cost} Z",
                callback_data=f"c:e:{notification.generation_id}:{token}",
            )
        ]])
        await bot.send_message(
            recipient,
            cube_content.lobby_invitation(notification.generation_id),
            reply_markup=keyboard,
        )
        return True

    if notification.kind == PUBLIC_NOTIFICATION:
        tg_id = notification.winner_tg_id
        if tg_id is None:
            raise ValueError("у объявления Куба нет победителя")
        nick = str(notification.winner_nick or "Игрок")
        title = nick if nick.startswith("@") else f"@{nick}"
        winner = hlink(title, f"tg://user?id={int(tg_id)}")
        await bot.send_message(
            chat_id=config.channel_id,
            message_thread_id=config.thread_id or None,
            text=cube_content.winner_announcement(
                winner,
                int(notification.prize_amount or 0),
                int(notification.participant_count or 0),
            ),
        )
        return True

    raise ValueError(f"неизвестный тип Cube notification: {notification.kind!r}")


def _notification_retry_delay(attempts: int) -> int:
    exponent = min(max(int(attempts or 0), 0), 20)
    return min(
        NOTIFICATION_RETRY_BASE_SECONDS * (2 ** exponent),
        NOTIFICATION_RETRY_MAX_SECONDS,
    )
