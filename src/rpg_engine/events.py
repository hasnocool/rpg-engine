"""Immutable facts emitted by the simulation."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from rpg_engine.models import (
    Ability,
    ActionBudget,
    ActiveEffect,
    EncounterState,
    Entity,
    Position,
    ReactionOffer,
    StrictModel,
)
from rpg_engine.resolution import Modifier
from rpg_engine.timeline import TimelineAdvanceSource, TimelineItem, TimeMode


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
    modifiers: list[Modifier] = Field(default_factory=list)
    total: int
    success: bool


class SavingThrowRolledEvent(EventBase):
    type: Literal["saving_throw_rolled"] = "saving_throw_rolled"
    actor_id: str
    source_id: str | None = None
    ability: Ability
    dc: int
    die_roll: int
    modifier: int
    modifiers: list[Modifier] = Field(default_factory=list)
    total: int
    success: bool


class AttackRolledEvent(EventBase):
    type: Literal["attack_rolled"] = "attack_rolled"
    attacker_id: str
    target_id: str
    weapon_id: str
    die_roll: int
    modifier: int
    modifiers: list[Modifier] = Field(default_factory=list)
    total: int
    armor_class: int
    hit: bool


class DamageAppliedEvent(EventBase):
    type: Literal["damage_applied"] = "damage_applied"
    source_id: str | None = None
    target_id: str
    damage_type: str
    raw_amount: int | None = None
    multiplier: float = 1.0
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


class InitiativeRolledEvent(EventBase):
    type: Literal["initiative_rolled"] = "initiative_rolled"
    encounter_id: str
    actor_id: str
    die_roll: int
    modifier: int
    modifiers: list[Modifier] = Field(default_factory=list)
    total: int


class EncounterStartedEvent(EventBase):
    type: Literal["encounter_started"] = "encounter_started"
    encounter: EncounterState


class EncounterEndedEvent(EventBase):
    type: Literal["encounter_ended"] = "encounter_ended"
    encounter_id: str
    participant_ids: list[str] = Field(default_factory=list)


class TurnStartedEvent(EventBase):
    type: Literal["turn_started"] = "turn_started"
    encounter_id: str
    actor_id: str
    round: int
    turn_index: int
    budget: ActionBudget


class TurnEndedEvent(EventBase):
    type: Literal["turn_ended"] = "turn_ended"
    actor_id: str
    encounter_id: str | None = None
    round: int | None = None
    next_actor_id: str | None = None


class ActionBudgetSpentEvent(EventBase):
    type: Literal["action_budget_spent"] = "action_budget_spent"
    encounter_id: str
    actor_id: str
    budget_kind: str
    amount: int
    remaining: int


class ResourceSpentEvent(EventBase):
    type: Literal["resource_spent"] = "resource_spent"
    actor_id: str
    resource_id: str
    amount: int
    remaining: int


class EffectActivatedEvent(EventBase):
    type: Literal["effect_activated"] = "effect_activated"
    effect: ActiveEffect


class EffectDurationTickedEvent(EventBase):
    type: Literal["effect_duration_ticked"] = "effect_duration_ticked"
    effect_instance_id: str
    remaining_turns: int


class EffectExpiredEvent(EventBase):
    type: Literal["effect_expired"] = "effect_expired"
    effect_instance_id: str
    effect_id: str
    target_id: str


class ConcentrationStartedEvent(EventBase):
    type: Literal["concentration_started"] = "concentration_started"
    actor_id: str
    effect_instance_id: str
    effect_id: str


class ConcentrationEndedEvent(EventBase):
    type: Literal["concentration_ended"] = "concentration_ended"
    actor_id: str
    effect_instance_id: str
    effect_id: str
    reason: str


class AreaTargetsResolvedEvent(EventBase):
    type: Literal["area_targets_resolved"] = "area_targets_resolved"
    effect_id: str
    source_id: str | None = None
    target_ids: list[str]


class TriggerRaisedEvent(EventBase):
    type: Literal["trigger_raised"] = "trigger_raised"
    trigger_id: str
    kind: str
    source_id: str | None = None
    target_id: str | None = None


class ReactionOfferedEvent(EventBase):
    type: Literal["reaction_offered"] = "reaction_offered"
    offer: ReactionOffer


class ReactionUsedEvent(EventBase):
    type: Literal["reaction_used"] = "reaction_used"
    trigger_id: str
    actor_id: str
    reaction_id: str


class TimelineConfiguredEvent(EventBase):
    type: Literal["timeline_configured"] = "timeline_configured"
    mode: TimeMode
    turn_quantum_ms: int
    turn_timeout_ms: int
    paused: bool
    wall_clock_anchor_ms: int | None = None


class TimelineItemScheduledEvent(EventBase):
    type: Literal["timeline_item_scheduled"] = "timeline_item_scheduled"
    item: TimelineItem


class TimelineItemCancelledEvent(EventBase):
    type: Literal["timeline_item_cancelled"] = "timeline_item_cancelled"
    item_id: str


class TimelineAdvancedEvent(EventBase):
    type: Literal["timeline_advanced"] = "timeline_advanced"
    source: TimelineAdvanceSource
    delta_ms: int
    time_ms: int
    wall_clock_anchor_ms: int | None = None
    backlog: bool = False


class TimelineItemFiredEvent(EventBase):
    type: Literal["timeline_item_fired"] = "timeline_item_fired"
    item: TimelineItem
    fired_at_ms: int
    rescheduled_item: TimelineItem | None = None


class TimelinePauseChangedEvent(EventBase):
    type: Literal["timeline_pause_changed"] = "timeline_pause_changed"
    paused: bool


Event = Annotated[
    EntityCreatedEvent
    | ActorMovedEvent
    | CheckRolledEvent
    | SavingThrowRolledEvent
    | AttackRolledEvent
    | DamageAppliedEvent
    | HealingAppliedEvent
    | ConditionAddedEvent
    | ConditionRemovedEvent
    | ActorDefeatedEvent
    | TimeAdvancedEvent
    | InitiativeRolledEvent
    | EncounterStartedEvent
    | EncounterEndedEvent
    | TurnStartedEvent
    | TurnEndedEvent
    | ActionBudgetSpentEvent
    | ResourceSpentEvent
    | EffectActivatedEvent
    | EffectDurationTickedEvent
    | EffectExpiredEvent
    | ConcentrationStartedEvent
    | ConcentrationEndedEvent
    | AreaTargetsResolvedEvent
    | TriggerRaisedEvent
    | ReactionOfferedEvent
    | ReactionUsedEvent
    | TimelineConfiguredEvent
    | TimelineItemScheduledEvent
    | TimelineItemCancelledEvent
    | TimelineAdvancedEvent
    | TimelineItemFiredEvent
    | TimelinePauseChangedEvent,
    Field(discriminator="type"),
]

EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


def parse_event(payload: object) -> Event:
    return EVENT_ADAPTER.validate_python(payload)
