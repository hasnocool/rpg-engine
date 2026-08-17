"""Immutable facts emitted by the simulation."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from rpg_engine.models import Ability, Entity, Position, StrictModel


class EventBase(StrictModel):
    sequence: int = 0
    campaign_id: str = ""
    rng_counters_after: dict[str, int] = Field(default_factory=dict)


class EntityCreatedEvent(EventBase):
    type: Literal["entity_created"] = "entity_created"
    entity: Entity


class ActorMovedEvent(EventBase):
    type: Literal["actor_moved"] = "actor_moved"
    actor_id: str
    position: Position


class CheckRolledEvent(EventBase):
    type: Literal["check_rolled"] = "check_rolled"
    actor_id: str
    ability: Ability
    dc: int
    die_roll: int
    modifier: int
    total: int
    success: bool


class AttackRolledEvent(EventBase):
    type: Literal["attack_rolled"] = "attack_rolled"
    attacker_id: str
    target_id: str
    weapon_id: str
    die_roll: int
    modifier: int
    total: int
    armor_class: int
    hit: bool


class DamageAppliedEvent(EventBase):
    type: Literal["damage_applied"] = "damage_applied"
    source_id: str | None = None
    target_id: str
    damage_type: str
    amount: int
    hp_after: int


class HealingAppliedEvent(EventBase):
    type: Literal["healing_applied"] = "healing_applied"
    source_id: str | None = None
    target_id: str
    amount: int
    hp_after: int


class ConditionAddedEvent(EventBase):
    type: Literal["condition_added"] = "condition_added"
    target_id: str
    condition: str


class ConditionRemovedEvent(EventBase):
    type: Literal["condition_removed"] = "condition_removed"
    target_id: str
    condition: str


class ActorDefeatedEvent(EventBase):
    type: Literal["actor_defeated"] = "actor_defeated"
    actor_id: str
    source_id: str | None = None


class TimeAdvancedEvent(EventBase):
    type: Literal["time_advanced"] = "time_advanced"
    minutes: int
    time_minutes: int


class TurnEndedEvent(EventBase):
    type: Literal["turn_ended"] = "turn_ended"
    actor_id: str


Event = Annotated[
    EntityCreatedEvent
    | ActorMovedEvent
    | CheckRolledEvent
    | AttackRolledEvent
    | DamageAppliedEvent
    | HealingAppliedEvent
    | ConditionAddedEvent
    | ConditionRemovedEvent
    | ActorDefeatedEvent
    | TimeAdvancedEvent
    | TurnEndedEvent,
    Field(discriminator="type"),
]

EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


def parse_event(payload: object) -> Event:
    return EVENT_ADAPTER.validate_python(payload)
