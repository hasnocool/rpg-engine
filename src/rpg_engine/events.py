"""Immutable facts emitted by the simulation."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AliasChoices, Field, TypeAdapter

from rpg_engine.models import (
    Ability,
    ActionBudget,
    ActiveEffect,
    CalendarState,
    ContainerState,
    DialogueSession,
    DynamicQuestState,
    EncounterState,
    Entity,
    NpcScheduleState,
    OffscreenEncounterRecord,
    Position,
    QuestProgress,
    ReactionOffer,
    ResourceNodeState,
    RumorState,
    SettlementState,
    StrictModel,
    WeatherState,
)
from rpg_engine.resolution import Modifier
from rpg_engine.timeline import TimeMode, TimelineAdvanceSource, TimelineItem


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


class NpcSpawnedEvent(EventBase):
    type: Literal["npc_spawned"] = "npc_spawned"
    template_id: str
    entity: Entity


class LocationDiscoveredEvent(EventBase):
    type: Literal["location_discovered"] = "location_discovered"
    actor_id: str
    location_id: str


class LocationExploredEvent(EventBase):
    type: Literal["location_explored"] = "location_explored"
    actor_id: str
    location_id: str


class LocationSearchedEvent(EventBase):
    type: Literal["location_searched"] = "location_searched"
    actor_id: str
    location_id: str
    ability: Ability
    die_roll: int
    modifier: int
    modifiers: list[Modifier] = Field(default_factory=list)
    total: int


class DiscoveryRevealedEvent(EventBase):
    type: Literal["discovery_revealed"] = "discovery_revealed"
    actor_id: str
    discovery_id: str
    location_ids: list[str] = Field(default_factory=list)
    connection_ids: list[str] = Field(default_factory=list)
    container_ids: list[str] = Field(default_factory=list)


class TravelCompletedEvent(EventBase):
    type: Literal["travel_completed"] = "travel_completed"
    actor_id: str
    connection_id: str
    from_location_id: str
    to_location_id: str
    minutes: int
    position: Position
    time_minutes: int


class ContainerCreatedEvent(EventBase):
    type: Literal["container_created"] = "container_created"
    container: ContainerState


class ContainerLootedEvent(EventBase):
    type: Literal["container_looted"] = "container_looted"
    actor_id: str
    container_id: str
    item_ids: list[str] = Field(default_factory=list)
    currency: dict[str, int] = Field(default_factory=dict)
    actor_item_ids_after: list[str]
    actor_currency_after: dict[str, int]
    container_item_ids_after: list[str]
    container_currency_after: dict[str, int]


class ItemEquippedEvent(EventBase):
    type: Literal["item_equipped"] = "item_equipped"
    actor_id: str
    item_id: str
    slot: str
    equipment_after: dict[str, str]
    equipped_item_ids_after: list[str]


class ItemUnequippedEvent(EventBase):
    type: Literal["item_unequipped"] = "item_unequipped"
    actor_id: str
    item_id: str
    slot: str
    equipment_after: dict[str, str]
    equipped_item_ids_after: list[str] = Field(
        validation_alias=AliasChoices("equipped_item_ids_after", "equicped_item_ids_after")
    )


class DialogueStartedEvent(EventBase):
    type: Literal["dialogue_started"] = "dialogue_started"
    session: DialogueSession


class DialogueAdvancedEvent(EventBase):
    type: Literal["dialogue_advanced"] = "dialogue_advanced"
    session_id: str
    option_id: str
    from_node_id: str
    to_node_id: str


class DialogueEndedEvent(EventBase):
    type: Literal["dialogue_ended"] = "dialogue_ended"
    session_id: str
    actor_id: str
    npc_id: str


class QuestStartedEvent(EventBase):
    type: Literal["quest_started"] = "quest_started"
    actor_id: str
    progress: QuestProgress


class QuestAdvancedEvent(EventBase):
    type: Literal["quest_advanced"] = "quest_advanced"
    actor_id: str
    quest_id: str
    trigger: str
    from_state: str
    to_state: str
    completed: bool


class TransactionCompletedEvent(EventBase):
    type: Literal["transaction_completed"] = "transaction_completed"
    buyer_id: str
    seller_id: str
    item_id: str
    quantity: int
    currency: str
    unit_price: int
    total: int
    buyer_item_ids_after: list[str]
    seller_item_ids_after: list[str]
    buyer_balance_after: int
    seller_balance_after: int


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


class LivingWorldInitializedEvent(EventBase):
    type: Literal["living_world_initialized"] = "living_world_initialized"
    initialized_at_ms: int


class CalendarAdvancedEvent(EventBase):
    type: Literal["calendar_advanced"] = "calendar_advanced"
    calendar: CalendarState


class WeatherChangedEvent(EventBase):
    type: Literal["weather_changed"] = "weather_changed"
    weather: WeatherState


class NpcScheduleAppliedEvent(EventBase):
    type: Literal["npc_schedule_applied"] = "npc_schedule_applied"
    schedule: NpcScheduleState
    position: Position


class FactionRelationChangedEvent(EventBase):
    type: Literal["faction_relation_changed"] = "faction_relation_changed"
    faction_a_id: str
    faction_b_id: str
    previous: int
    current: int
    reason: str


class ReputationChangedEvent(EventBase):
    type: Literal["reputation_changed"] = "reputation_changed"
    actor_id: str
    faction_id: str
    previous: int
    current: int
    reason: str


class SettlementInitializedEvent(EventBase):
    type: Literal["settlement_initialized"] = "settlement_initialized"
    settlement: SettlementState


class SettlementEconomyTickedEvent(EventBase):
    type: Literal["settlement_economy_ticked"] = "settlement_economy_ticked"
    settlement: SettlementState


class OffscreenEncounterResolvedEvent(EventBase):
    type: Literal["offscreen_encounter_resolved"] = "offscreen_encounter_resolved"
    record: OffscreenEncounterRecord


class RumorGeneratedEvent(EventBase):
    type: Literal["rumor_generated"] = "rumor_generated"
    rumor: RumorState


class DynamicQuestGeneratedEvent(EventBase):
    type: Literal["dynamic_quest_generated"] = "dynamic_quest_generated"
    quest: DynamicQuestState


class DynamicQuestUpdatedEvent(EventBase):
    type: Literal["dynamic_quest_updated"] = "dynamic_quest_updated"
    quest: DynamicQuestState
    actor_id: str | None = None
    reward_currency: str | None = None
    reward_amount: int = 0
    actor_balance_after: int | None = None


class ResourceNodeInitializedEvent(EventBase):
    type: Literal["resource_node_initialized"] = "resource_node_initialized"
    node: ResourceNodeState


class ResourceHarvestedEvent(EventBase):
    type: Literal["resource_harvested"] = "resource_harvested"
    actor_id: str
    node_id: str
    item_id: str
    amount: int
    node_amount_after: int
    actor_item_ids_after: list[str]


class ResourceRegeneratedEvent(EventBase):
    type: Literal["resource_regenerated"] = "resource_regenerated"
    node_id: str
    amount: int
    amount_after: int
    last_regen_minute: int
    weather_condition: str | None = None


Event = Annotated[
    EntityCreatedEvent
    | NpcSpawnedEvent
    | LocationDiscoveredEvent
    | LocationExploredEvent
    | LocationSearchedEvent
    | DiscoveryRevealedEvent
    | TravelCompletedEvent
    | ContainerCreatedEvent
    | ContainerLootedEvent
    | ItemEquippedEvent
    | ItemUnequippedEvent
    | DialogueStartedEvent
    | DialogueAdvancedEvent
    | DialogueEndedEvent
    | QuestStartedEvent
    | QuestAdvancedEvent
    | TransactionCompletedEvent
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
    | TimelinePauseChangedEvent
    | LivingWorldInitializedEvent
    | CalendarAdvancedEvent
    | WeatherChangedEvent
    | NpcScheduleAppliedEvent
    | FactionRelationChangedEvent
    | ReputationChangedEvent
    | SettlementInitializedEvent
    | SettlementEconomyTickedEvent
    | OffscreenEncounterResolvedEvent
    | RumorGeneratedEvent
    | DynamicQuestGeneratedEvent
    | DynamicQuestUpdatedEvent
    | ResourceNodeInitializedEvent
    | ResourceHarvestedEvent
    | ResourceRegeneratedEvent,
    Field(discriminator="type"),
]

EVENT_ADAPTER = TypeAdapter(Event)


def parse_event(payload: object) -> Event:
    return EVENT_ADAPTER.validate_python(payload)