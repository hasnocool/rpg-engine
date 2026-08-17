"""Deterministic trigger/reaction extension points for tactical rulesets."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from pydantic import Field

from rpg_engine.models import ReactionOffer, StrictModel, WorldState


class TriggerContext(StrictModel):
    id: str
    kind: str
    source_id: str | None = None
    target_id: str | None = None
    payload: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class TacticalHook(Protocol):
    name: str

    def triggers_for(self, event: object, world: WorldState) -> Iterable[TriggerContext]: ...

    def reactions_for(
        self, trigger: TriggerContext, world: WorldState
    ) -> Iterable[ReactionOffer]: ...


class HookRegistry:
    def __init__(self, hooks: Iterable[TacticalHook] = ()) -> None:
        self._hooks = tuple(sorted(hooks, key=lambda hook: hook.name))

    def collect(
        self, event: object, world: WorldState
    ) -> list[tuple[TriggerContext, list[ReactionOffer]]]:
        collected: list[tuple[TriggerContext, list[ReactionOffer]]] = []
        for hook in self._hooks:
            for trigger in sorted(hook.triggers_for(event, world), key=lambda item: item.id):
                offers = sorted(
                    hook.reactions_for(trigger, world),
                    key=lambda item: (item.actor_id, item.reaction_id, item.id),
                )
                collected.append((trigger, list(offers)))
        return collected
