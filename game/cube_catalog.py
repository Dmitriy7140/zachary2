"""Версионируемый каталог комнат и предметных действий Куба.

Persisted keys из этого модуля являются публичным контрактом сохранённых
поколений. Новые определения можно добавлять в каталог сразу, но менять pool
генератора нужно новой :class:`LayoutPolicy`: один и тот же ``seed`` и
``layout_version`` обязаны продолжать описывать один лабиринт.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from game.items import ITEMS


ROOM_START = "start"
ROOM_PRIZE = "prize"
ROOM_NEUTRAL = "neutral"
ROOM_HAZARD = "hazard"
ROOM_ANOMALY = "anomaly"

MAP_CATEGORY_DANGEROUS = "dangerous"
MAP_CATEGORY_NEUTRAL = "neutral"
MAP_CATEGORY_USEFUL = "useful"

OBSERVATION_QUIET = "quiet"
OBSERVATION_HAZARD = "hazard"
OBSERVATION_ANOMALY = "anomaly"
OBSERVATION_UNREADABLE = "unreadable"

_CALLBACK_KEY_RE = re.compile(r"[a-z0-9_-]+")


class CubeItemKind(str, Enum):
    TOOL = "tool"
    CONSUMABLE = "consumable"


class EffectBehavior(str, Enum):
    REVEAL_NEIGHBOR = "reveal_neighbor"
    BOUNCE_ONCE = "bounce_once"
    DARKEN_VIEW = "darken_view"
    TRANSFER = "transfer"


class EffectPlacement(str, Enum):
    NEIGHBOR_TARGET = "neighbor_target"
    SINGLE = "single"
    SAME_COMPONENT_TRANSFER = "same_component_transfer"
    PAIRED_SAME_COMPONENT = "paired_same_component"


class EffectArgKind(str, Enum):
    NONE = "none"
    DIRECTION = "direction"
    TARGET_ROOM_CODE = "target_room_code"


@dataclass(frozen=True)
class CubeItemUse:
    """Как предмет ведёт себя на экране выбора и при неверной попытке."""

    item_key: str
    kind: CubeItemKind
    wrong_consume_qty: int = 1

    @property
    def is_consumable(self) -> bool:
        return self.kind is CubeItemKind.CONSUMABLE


@dataclass(frozen=True)
class HazardDefinition:
    """Предметный барьер с неизменяемым persisted key."""

    key: str
    description_key: str
    solution_item_key: str
    success_consume_qty: int

    # Совместимые имена для существующих call sites и тестовых спецификаций.
    @property
    def kind(self) -> str:
        return self.key

    @property
    def item_key(self) -> str:
        return self.solution_item_key

    @property
    def consume_qty(self) -> int:
        return self.success_consume_qty


@dataclass(frozen=True)
class EffectDefinition:
    """Аномалия, сведённая к одному из поддерживаемых движком поведений."""

    key: str
    description_key: str
    behavior: EffectBehavior
    placement: EffectPlacement
    map_category: str
    arg_kind: EffectArgKind = EffectArgKind.NONE

    @property
    def shows_target_code(self) -> bool:
        return self.arg_kind is EffectArgKind.TARGET_ROOM_CODE


@dataclass(frozen=True)
class LayoutPolicy:
    """Замороженные ordered pools конкретной версии генератора."""

    version: int
    neutral_description_keys: tuple[str, ...]
    hazard_keys: tuple[str, ...]
    effect_keys: tuple[str, ...]


CUBE_ITEM_USES = (
    CubeItemUse("bucket", CubeItemKind.TOOL),
    CubeItemUse("rod", CubeItemKind.TOOL),
    CubeItemUse("bait_1", CubeItemKind.CONSUMABLE),
    CubeItemUse("znak", CubeItemKind.TOOL),
    CubeItemUse("lockpicks", CubeItemKind.TOOL),
    CubeItemUse("bait_3", CubeItemKind.CONSUMABLE),
    CubeItemUse("milk_can", CubeItemKind.CONSUMABLE),
    CubeItemUse("egg", CubeItemKind.CONSUMABLE),
)
CUBE_ITEM_BY_KEY = {definition.item_key: definition for definition in CUBE_ITEM_USES}

HAZARD_DEFINITIONS = (
    HazardDefinition("flooded_floor", "hazard.flooded_floor", "bucket", 0),
    HazardDefinition("chasm_lever", "hazard.chasm_lever", "rod", 0),
    HazardDefinition("mutant_leeches", "hazard.mutant_leeches", "bait_1", 1),
    HazardDefinition("wire_net", "hazard.wire_net", "znak", 0),
    HazardDefinition("locked_hatch", "hazard.locked_hatch", "lockpicks", 0),
    HazardDefinition("shark_guard", "hazard.shark_guard", "bait_3", 1),
    HazardDefinition("laser_grid", "hazard.laser_grid", "milk_can", 1),
    HazardDefinition("invisible_cutters", "hazard.invisible_cutters", "egg", 1),
)
HAZARD_BY_KIND = {definition.key: definition for definition in HAZARD_DEFINITIONS}

EFFECT_DEFINITIONS = (
    EffectDefinition(
        "archive",
        "anomaly.archive",
        EffectBehavior.REVEAL_NEIGHBOR,
        EffectPlacement.NEIGHBOR_TARGET,
        MAP_CATEGORY_USEFUL,
        EffectArgKind.DIRECTION,
    ),
    EffectDefinition(
        "echo",
        "anomaly.echo",
        EffectBehavior.BOUNCE_ONCE,
        EffectPlacement.SINGLE,
        MAP_CATEGORY_DANGEROUS,
    ),
    EffectDefinition(
        "dark",
        "anomaly.dark",
        EffectBehavior.DARKEN_VIEW,
        EffectPlacement.SINGLE,
        MAP_CATEGORY_DANGEROUS,
    ),
    EffectDefinition(
        "vector",
        "anomaly.vector",
        EffectBehavior.TRANSFER,
        EffectPlacement.SAME_COMPONENT_TRANSFER,
        MAP_CATEGORY_NEUTRAL,
        EffectArgKind.TARGET_ROOM_CODE,
    ),
    EffectDefinition(
        "tunnel",
        "anomaly.tunnel",
        EffectBehavior.TRANSFER,
        EffectPlacement.PAIRED_SAME_COMPONENT,
        MAP_CATEGORY_NEUTRAL,
        EffectArgKind.TARGET_ROOM_CODE,
    ),
)
EFFECT_BY_KIND = {definition.key: definition for definition in EFFECT_DEFINITIONS}
EFFECT_ALIASES = {"echo_bounce": "echo"}

NEUTRAL_DESCRIPTION_KEYS = (
    "neutral.white",
    "neutral.amber",
    "neutral.blue",
    "neutral.green",
    "neutral.red",
    "neutral.violet",
    "neutral.rust",
    "neutral.mirror",
)

LAYOUT_V1 = LayoutPolicy(
    version=1,
    # Эти tuples намеренно не выводятся из актуального каталога. Расширение
    # definitions не должно незаметно менять старую seed-policy.
    neutral_description_keys=(
        "neutral.white",
        "neutral.amber",
        "neutral.blue",
        "neutral.green",
        "neutral.red",
        "neutral.violet",
        "neutral.rust",
        "neutral.mirror",
    ),
    hazard_keys=(
        "flooded_floor",
        "chasm_lever",
        "mutant_leeches",
        "wire_net",
        "locked_hatch",
        "shark_guard",
        "laser_grid",
        "invisible_cutters",
    ),
    # Порядок здесь описывает состав v1. Размещение по-прежнему определяется
    # EffectPlacement и сохраняет прежнюю последовательность RNG-вызовов.
    effect_keys=("tunnel", "vector", "archive", "echo", "dark"),
)
LAYOUT_POLICIES = {LAYOUT_V1.version: LAYOUT_V1}
CURRENT_LAYOUT_VERSION = max(LAYOUT_POLICIES)


def hazard_definition(kind: str | None) -> HazardDefinition | None:
    return HAZARD_BY_KIND.get(kind or "")


def effect_definition(kind: str | None) -> EffectDefinition | None:
    canonical = EFFECT_ALIASES.get(kind or "", kind or "")
    return EFFECT_BY_KIND.get(canonical)


def cube_item_use(item_key: str | None) -> CubeItemUse | None:
    return CUBE_ITEM_BY_KEY.get(item_key or "")


def layout_policy(version: int) -> LayoutPolicy:
    try:
        return LAYOUT_POLICIES[version]
    except KeyError as exc:
        raise ValueError(f"unsupported Cube layout version: {version}") from exc


def layout_item_keys(version: int) -> tuple[str, ...]:
    """Предметы, которые действительно могут быть решением в этой layout-policy."""
    policy = layout_policy(version)
    solutions = {
        HAZARD_BY_KIND[key].solution_item_key for key in policy.hazard_keys
    }
    return tuple(
        definition.item_key
        for definition in CUBE_ITEM_USES
        if definition.item_key in solutions
    )


def room_map_category(kind: str, effect_kind: str | None = None) -> str:
    effect = effect_definition(effect_kind)
    if effect is not None:
        return effect.map_category
    if kind == ROOM_HAZARD:
        return MAP_CATEGORY_DANGEROUS
    if kind == ROOM_PRIZE:
        return MAP_CATEGORY_USEFUL
    return MAP_CATEGORY_NEUTRAL


def room_observation_category(kind: str, effect_kind: str | None = None) -> str:
    if kind == ROOM_PRIZE:
        return OBSERVATION_UNREADABLE
    if kind == ROOM_HAZARD:
        return OBSERVATION_HAZARD
    if effect_definition(effect_kind) is not None or kind == ROOM_ANOMALY:
        return OBSERVATION_ANOMALY
    return OBSERVATION_QUIET


def effect_has_behavior(kind: str | None, behavior: EffectBehavior) -> bool:
    definition = effect_definition(kind)
    return definition is not None and definition.behavior is behavior


def _validate_catalog() -> None:
    if len(CUBE_ITEM_BY_KEY) != len(CUBE_ITEM_USES):
        raise RuntimeError("Cube item keys must be unique")
    if len(HAZARD_BY_KIND) != len(HAZARD_DEFINITIONS):
        raise RuntimeError("Cube hazard keys must be unique")
    if len(EFFECT_BY_KIND) != len(EFFECT_DEFINITIONS):
        raise RuntimeError("Cube effect keys must be unique")

    for item in CUBE_ITEM_USES:
        if item.item_key not in ITEMS:
            raise RuntimeError(f"Cube references unknown item: {item.item_key}")
        if _CALLBACK_KEY_RE.fullmatch(item.item_key) is None:
            raise RuntimeError(f"Cube item key is not callback-safe: {item.item_key}")
        if len(item.item_key.encode()) > 20:
            raise RuntimeError(f"Cube item key is too long for callback: {item.item_key}")
        # Текущий callback/UI и правило анти-подсказки рассчитаны ровно на
        # одну потерянную единицу. Другую цену нужно вводить вместе с новым
        # экранным и storage-контрактом, а не только числом в каталоге.
        if item.wrong_consume_qty != 1:
            raise RuntimeError("wrong Cube item use must consume exactly one")

    if {
        hazard.solution_item_key for hazard in HAZARD_DEFINITIONS
    } != set(CUBE_ITEM_BY_KEY):
        raise RuntimeError("Cube item choices and hazard solutions are out of sync")
    for hazard in HAZARD_DEFINITIONS:
        item = CUBE_ITEM_BY_KEY[hazard.solution_item_key]
        expected = 1 if item.is_consumable else 0
        if hazard.success_consume_qty != expected:
            raise RuntimeError(f"Cube hazard has invalid success cost: {hazard.key}")

    known_categories = {
        MAP_CATEGORY_DANGEROUS,
        MAP_CATEGORY_NEUTRAL,
        MAP_CATEGORY_USEFUL,
    }
    behavior_contracts = {
        EffectBehavior.REVEAL_NEIGHBOR: (
            {EffectPlacement.NEIGHBOR_TARGET},
            EffectArgKind.DIRECTION,
        ),
        EffectBehavior.BOUNCE_ONCE: (
            {EffectPlacement.SINGLE},
            EffectArgKind.NONE,
        ),
        EffectBehavior.DARKEN_VIEW: (
            {EffectPlacement.SINGLE},
            EffectArgKind.NONE,
        ),
        EffectBehavior.TRANSFER: (
            {
                EffectPlacement.SAME_COMPONENT_TRANSFER,
                EffectPlacement.PAIRED_SAME_COMPONENT,
            },
            EffectArgKind.TARGET_ROOM_CODE,
        ),
    }
    for effect in EFFECT_DEFINITIONS:
        if effect.map_category not in known_categories:
            raise RuntimeError(f"Cube effect has invalid map category: {effect.key}")
        placements, arg_kind = behavior_contracts[effect.behavior]
        if effect.placement not in placements or effect.arg_kind is not arg_kind:
            raise RuntimeError(f"Cube effect has inconsistent behavior: {effect.key}")

    for alias, canonical in EFFECT_ALIASES.items():
        if alias in EFFECT_BY_KIND or canonical not in EFFECT_BY_KIND:
            raise RuntimeError(f"Cube effect alias is invalid: {alias}")

    for version, policy in LAYOUT_POLICIES.items():
        if version != policy.version or version <= 0:
            raise RuntimeError("Cube layout policy has an invalid version")
        if not policy.neutral_description_keys:
            raise RuntimeError("Cube layout needs neutral room descriptions")
        if len(set(policy.neutral_description_keys)) != len(
            policy.neutral_description_keys
        ):
            raise RuntimeError(f"Cube layout {policy.version} repeats neutral rooms")
        if len(set(policy.hazard_keys)) != len(policy.hazard_keys):
            raise RuntimeError(f"Cube layout {policy.version} repeats hazards")
        if len(set(policy.effect_keys)) != len(policy.effect_keys):
            raise RuntimeError(f"Cube layout {policy.version} repeats effects")
        if any(
            key not in NEUTRAL_DESCRIPTION_KEYS
            for key in policy.neutral_description_keys
        ):
            raise RuntimeError(f"Cube layout {policy.version} has unknown neutral room")
        if any(key not in HAZARD_BY_KIND for key in policy.hazard_keys):
            raise RuntimeError(f"Cube layout {policy.version} has unknown hazard")
        if any(key not in EFFECT_BY_KIND for key in policy.effect_keys):
            raise RuntimeError(f"Cube layout {policy.version} has unknown effect")


_validate_catalog()


# Compatibility aliases. New code should prefer the definitions/accessors above.
HazardSpec = HazardDefinition
HAZARD_SPECS = HAZARD_DEFINITIONS
ITEM_CONSUMPTION = {
    definition.solution_item_key: definition.success_consume_qty
    for definition in HAZARD_DEFINITIONS
}
TRANSFER_EFFECTS = frozenset(
    definition.key
    for definition in EFFECT_DEFINITIONS
    if definition.behavior is EffectBehavior.TRANSFER
)

EFFECT_ARCHIVE = "archive"
EFFECT_ECHO = "echo"
EFFECT_DARK = "dark"
EFFECT_VECTOR = "vector"
EFFECT_TUNNEL = "tunnel"
