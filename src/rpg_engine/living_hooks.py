"""Deterministic extension hooks for living-world ecology rules."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from rpg_engine.models import ResourceNodeState, WeatherState, WorldState


class EcologyHook(Protocol):
    """Ruleset hook that can scale resource regeneration without mutating state."""

    name: str

    def regen_multiplier(
        self,
        node: ResourceNodeState,
        weather: WeatherState | None,
        world: WorldState,
    ) -> float: ...


class EcologyHookRegistry:
    """Stable-order ecology hook composition."""

    def __init__(self, hooks: Iterable[EcologyHook] = ()) -> None:
        self._hooks = tuple(sorted(hooks, key=lambda hook: hook.name))

    def regen_multiplier(
        self,
        node: ResourceNodeState,
        weather: WeatherState | None,
        world: WorldState,
    ) -> float:
        multiplier = 1.0
        for hook in self._hooks:
            multiplier *= max(0.0, float(hook.regen_multiplier(node, weather, world)))
        return multiplier