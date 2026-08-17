"""Event reducer for deterministic reconstruction between snapshots."""

from __future__ import annotations

from rpg_engine.events import (
    ActorMovedEvent,
    ConditionAddedEvent,
    ConditionRemovedEvent,
    DamageAppliedEvent,
    EntityCreatedEvent,
    Event,
    HealingAppliedEvent,
    TimeAdvancedEvent,
)
from rpg_engine.models import WorldState


def apply_event(world: WorldState, event: Event) -> None:
    if isinstance(event, EntityCreatedEvent):
        world.entities[event.entity.id] = event.entity.model_copy(deep=True)
    elif isinstance(event, ActorMovedEvent):
        world.entities[event.actor_id].position = event.position.model_copy(deep=True)
    elif isinstance(event, DamageAppliedEvent):
        health = world.entities[event.target_id].health
        if health is not None:
            health.current = event.hp_after
    elif isinstance(event, HealingAppliedEvent):
        health = world.entities[event.target_id].health
        if health is not None:
            health.current = event.hp_after
    elif isinstance(event, ConditionAddedEvent):
        world.entities[event.target_id].conditions.add(event.condition)
    elif isinstance(event, ConditionRemovedEvent):
        world.entities[event.target_id].conditions.discard(event.condition)
    elif isinstance(event, TimeAdvancedEvent):
        world.time_minutes = event.time_minutes
    world.rng_counters.clear()
    world.rng_counters.update(event.rng_counters_after)
    world.sequence = max(world.sequence, event.sequence)
    world.event_count = max(world.event_count, event.sequence)
