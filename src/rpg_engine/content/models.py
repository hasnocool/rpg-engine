"""Validated content-pack models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from rpg_engine.models import Ability, ActionKind, Entity, StrictModel, WeaponSpec
from rpg_engine.spatial import TargetingContract


class EffectOperation(StrictModel):
    type: Literal["damage", "heal", "add_condition", "remove_condition"]
    amount: str | None = None
    damage_type: str = "untyped"
    condition: str | None = None


class EffectSpec(StrictModel):
    id: str
    name: str
    operations: list[EffectOperation] = Field(default_factory=list)
    action_cost: ActionKind | None = ActionKind.ACTION
    duration_turns: int | None = Field(default=None, ge=1)
    expires_on: Literal["start", "end"] = "end"
    concentration: bool = False
    resource_costs: dict[str, int] = Field(default_factory=dict)
    targeting: TargetingContract = Field(default_factory=TargetingContract)


class ItemSpec(StrictModel):
    id: str
    name: str
    value: int = Field(default=0, ge=0)
    weight: float = Field(default=0.0, ge=0)
    tags: set[str] = Field(default_factory=set)
    equip_slot: str | None = None
    effect_id: str | None = None


class ContainerTemplateSpec(StrictModel):
    id: str
    name: str
    location_id: str | None = None
    item_ids: list[str] = Field(default_factory=list)
    currency: dict[str, int] = Field(default_factory=dict)
    locked: bool = False


class WorldLocationSpec(StrictModel):
    id: str
    name: str
    description: str = ""
    region: str | None = None
    tags: set[str] = Field(default_factory=set)


class WorldConnectionSpec(StrictModel):
    id: str
    from_location_id: str
    to_location_id: str
    travel_minutes: int = Field(default=10, ge=0)
    bidirectional: bool = True
    hidden: bool = False
    tags: set[str] = Field(default_factory=set)

    def connects(self, source_id: str, destination_id: str) -> bool:
        if self.from_location_id == source_id and self.to_location_id == destination_id:
            return True
        return (
            self.bidirectional
            and self.to_location_id == source_id
            and self.from_location_id == destination_id
        )


class DiscoverySpec(StrictModel):
    id: str
    location_id: str
    name: str
    description: str = ""
    ability: Ability = Ability.WISDOM
    dc: int = Field(default=10, ge=0)
    reveal_location_ids: list[str] = Field(default_factory=list)
    reveal_connection_ids: list[str] = Field(default_factory=list)
    reveal_container_ids: list[str] = Field(default_factory=list)


class NpcTemplateSpec(StrictModel):
    id: str
    entity: Entity
    dialogue_id: str | None = None
    merchant_id: str | None = None
    schedule_id: str | None = None


class DialogueCheckSpec(StrictModel):
    ability: Ability
    dc: int


class QuestActionSpec(StrictModel):
    type: Literal["start", "trigger"]
    quest_id: str
    trigger: str | None = None

    @model_validator(mode="after")
    def validate_trigger(self) -> QuestActionSpec:
        if self.type == "trigger" and not self.trigger:
            raise ValueError("quest trigger action requires a trigger")
        return self


class DialogueOptionSpec(StrictModel):
    id: str
    text: str
    next_node_id: str | None = None
    success_node_id: str | None = None
    failure_node_id: str | None = None
    check: DialogueCheckSpec | None = None
    requires_quest_states: dict[str, set[str]] = Field(default_factory=dict)
    quest_actions: list[QuestActionSpec] = Field(default_factory=list)
    end_dialogue: bool = False


class DialogueNodeSpec(StrictModel):
    id: str
    text: str
    options: list[DialogueOptionSpec] = Field(default_factory=list)


class DialogueSpec(StrictModel):
    id: str
    start_node_id: str
    nodes: dict[str, DialogueNodeSpec]

    @model_validator(mode="after")
    def validate_nodes(self) -> DialogueSpec:
        if self.start_node_id not in self.nodes:
            raise ValueError("dialogue start node does not exist")
        return self


class QuestTransitionSpec(StrictModel):
    from_state: str
    trigger: str
    to_state: str


class QuestSpec(StrictModel):
    id: str
    name: str
    description: str = ""
    initial_state: str
    states: set[str]
    terminal_states: set[str] = Field(default_factory=set)
    transitions: list[QuestTransitionSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_states(self) -> QuestSpec:
        if self.initial_state not in self.states:
            raise ValueError("quest initial state must be declared")
        if not self.terminal_states <= self.states:
            raise ValueError("quest terminal states must be declared")
        seen: set[tuple[str, str]] = set()
        for transition in self.transitions:
            if transition.from_state not in self.states or transition.to_state not in self.states:
                raise ValueError("quest transition references undeclared state")
            key = (transition.from_state, transition.trigger)
            if key in seen:
                raise ValueError("quest has ambiguous duplicate transition")
            seen.add(key)
        return self


class MerchantSpec(StrictModel):
    id: str
    currency: str = "gold"
    stock_item_ids: list[str] = Field(default_factory=list)
    funds: int = Field(default=0, ge=0)
    sell_multiplier: float = Field(default=1.0, ge=0)
    buy_multiplier: float = Field(default=0.5, ge=0)
    price_overrides: dict[str, int] = Field(default_factory=dict)


class SeasonSpec(StrictModel):
    name: str
    start_day: int = Field(ge=1)


class CalendarSpec(StrictModel):
    id: str
    minutes_per_day: int = Field(default=1440, gt=0)
    days_per_year: int = Field(default=360, gt=0)
    starting_year: int = Field(default=1, ge=1)
    seasons: list[SeasonSpec] = Field(
        default_factory=lambda: [SeasonSpec(name="default", start_day=1)]
    )

    @model_validator(mode="after")
    def validate_seasons(self) -> CalendarSpec:
        starts = [season.start_day for season in self.seasons]
        if not starts or starts[0] != 1:
            raise ValueError("calendar seasons must start at day 1")
        if starts != sorted(set(starts)):
            raise ValueError("calendar season start days must be unique and sorted")
        if starts[-1] > self.days_per_year:
            raise ValueError("calendar season start day exceeds days_per_year")
        return self


class WeatherOptionSpec(StrictModel):
    condition: str
    weight: int = Field(default=1, gt=0)
    temperature_min_c: int = 10
    temperature_max_c: int = 20
    precipitation: float = Field(default=0.0, ge=0.0, le=1.0)
    wind_min_kph: int = Field(default=0, ge=0)
    wind_max_kph: int = Field(default=10, ge=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> WeatherOptionSpec:
        if self.temperature_min_c > self.temperature_max_c:
            raise ValueError("weather minimum temperature exceeds maximum")
        if self.wind_min_kph > self.wind_max_kph:
            raise ValueError("weather minimum wind exceeds maximum")
        return self


class WeatherProfileSpec(StrictModel):
    id: str
    region_id: str
    update_interval_minutes: int = Field(default=180, gt=0)
    options: list[WeatherOptionSpec] = Field(min_length=1)


class NpcScheduleEntrySpec(StrictModel):
    start_minute: int = Field(ge=0, lt=1440)
    location_id: str
    activity: str = "idle"


class NpcScheduleSpec(StrictModel):
    id: str
    tick_interval_minutes: int = Field(default=30, gt=0)
    entries: list[NpcScheduleEntrySpec] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_entries(self) -> NpcScheduleSpec:
        starts = [entry.start_minute for entry in self.entries]
        if starts != sorted(set(starts)):
            raise ValueError("NPC schedule entries must have unique sorted start times")
        return self


class FactionSpec(StrictModel):
    id: str
    name: str
    base_relations: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_relations(self) -> FactionSpec:
        if any(not -100 <= value <= 100 for value in self.base_relations.values()):
            raise ValueError("faction relations must be between -100 and 100")
        return self


class SettlementSpec(StrictModel):
    id: str
    name: str
    location_id: str
    faction_id: str | None = None
    population: int = Field(default=0, ge=0)
    treasury: int = Field(default=0, ge=0)
    prosperity: float = Field(default=1.0, ge=0.0, le=2.0)
    initial_stocks: dict[str, int] = Field(default_factory=dict)
    production_per_tick: dict[str, int] = Field(default_factory=dict)
    consumption_per_tick: dict[str, int] = Field(default_factory=dict)
    income_per_tick: int = Field(default=0, ge=0)
    expenses_per_tick: int = Field(default=0, ge=0)
    tick_interval_minutes: int = Field(default=360, gt=0)

    @model_validator(mode="after")
    def validate_stock_values(self) -> SettlementSpec:
        stock_values = [
            *self.initial_stocks.values(),
            *self.production_per_tick.values(),
            *self.consumption_per_tick.values(),
        ]
        if any(value < 0 for value in stock_values):
            raise ValueError("settlement stock/flow values cannot be negative")
        return self


class DynamicQuestTemplateSpec(StrictModel):
    id: str
    title: str
    description: str
    target_location_ids: list[str] = Field(min_length=1)
    reward_currency: str = "gold"
    reward_amount: int = Field(default=0, ge=0)
    expires_after_minutes: int | None = Field(default=None, gt=0)


class RumorTemplateSpec(StrictModel):
    id: str
    text: str
    location_id: str
    weight: int = Field(default=1, gt=0)
    interval_minutes: int = Field(default=360, gt=0)
    expires_after_minutes: int | None = Field(default=720, gt=0)
    quest_template_id: str | None = None


class ResourceNodeSpec(StrictModel):
    id: str
    location_id: str
    item_id: str
    capacity: int = Field(gt=0)
    initial_amount: int = Field(ge=0)
    regen_amount: int = Field(default=1, gt=0)
    regen_interval_minutes: int = Field(default=360, gt=0)

    @model_validator(mode="after")
    def validate_initial_amount(self) -> ResourceNodeSpec:
        if self.initial_amount > self.capacity:
            raise ValueError("resource initial amount exceeds capacity")
        return self


class ContentManifest(StrictModel):
    id: str
    name: str
    version: str
    ruleset: str = "d20"


class ContentRegistry(StrictModel):
    manifest: ContentManifest | None = None
    weapons: dict[str, WeaponSpec] = Field(default_factory=dict)
    effects: dict[str, EffectSpec] = Field(default_factory=dict)
    items: dict[str, ItemSpec] = Field(default_factory=dict)
    containers: dict[str, ContainerTemplateSpec] = Field(default_factory=dict)
    locations: dict[str, WorldLocationSpec] = Field(default_factory=dict)
    connections: dict[str, WorldConnectionSpec] = Field(default_factory=dict)
    discoveries: dict[str, DiscoverySpec] = Field(default_factory=dict)
    npc_templates: dict[str, NpcTemplateSpec] = Field(default_factory=dict)
    dialogues: dict[str, DialogueSpec] = Field(default_factory=dict)
    quests: dict[str, QuestSpec] = Field(default_factory=dict)
    merchants: dict[str, MerchantSpec] = Field(default_factory=dict)
    calendars: dict[str, CalendarSpec] = Field(default_factory=dict)
    weather_profiles: dict[str, WeatherProfileSpec] = Field(default_factory=dict)
    npc_schedules: dict[str, NpcScheduleSpec] = Field(default_factory=dict)
    factions: dict[str, FactionSpec] = Field(default_factory=dict)
    settlements: dict[str, SettlementSpec] = Field(default_factory=dict)
    dynamic_quest_templates: dict[str, DynamicQuestTemplateSpec] = Field(default_factory=dict)
    rumor_templates: dict[str, RumorTemplateSpec] = Field(default_factory=dict)
    resource_nodes: dict[str, ResourceNodeSpec] = Field(default_factory=dict)

    @classmethod
    def with_core_defaults(cls) -> ContentRegistry:
        unarmed = WeaponSpec(
            id="unarmed",
            name="Unarmed Strike",
            damage="1d1",
            damage_type="bludgeoning",
        )
        return cls(
            weapons={"unarmed": unarmed},
            items={
                "unarmed": ItemSpec(
                    id="unarmed",
                    name="Unarmed Strike",
                    value=0,
                    tags={"weapon", "natural"},
                )
            },
        )