"""Authoritative presentation-agnostic simulation engine with adventure extensions."""

from __future__ import annotations

from rpg_engine.adventure import AdventureError, AdventureRuntime
from rpg_engine.commands import Command
from rpg_engine.content.models import ContentRegistry
from rpg_engine.events import Event
from rpg_engine.hooks import HookRegistry
from rpg_engine.models import WorldState
from rpg_engine.rules.base import RulesRuntime
from rpg_engine.spatial import SpatialAdapter
from rpg_engine.tactical_engine import SimulationEngine as TacticalSimulationEngine
from rpg_engine.tactical_engine import SimulationError


class SimulationEngine(TacticalSimulationEngine):
    """v0.1/v0.2 engine plus the v0.3 adventure command domain."""

    def __init__(
        self,
        world: WorldState,
        *,
        rules: RulesRuntime | None = None,
        content: ContentRegistry | None = None,
        spatial: SpatialAdapter | None = None,
        hooks: HookRegistry | None = None,
    ) -> None:
        super().__init__(
            world,
            rules=rules,
            content=content,
            spatial=spatial,
            hooks=hooks,
        )
        self.adventure = AdventureRuntime(
            self.world,
            content=self.content,
            rules=self.rules,
            rng=self.rng,
        )

    def execute(self, command: Command) -> list[Event]:
        if AdventureRuntime.handles(command):
            try:
                events = self.adventure.execute(command)
            except AdventureError as exc:
                raise SimulationError(str(exc)) from exc
            return self._stamp(self._expand_hooks(events))
        return super().execute(command)


__all__ = ["SimulationEngine", "SimulationError"]
