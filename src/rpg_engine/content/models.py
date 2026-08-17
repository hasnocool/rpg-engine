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
        for transition in self.transitions:
            if transition.from_state not in self.states or transition.to_state not in self.states:
                raise ValueError("quest transition references undeclared state")
        return self


class MerchantSpec(StrictModel):
    id: str
    currency: str = "gold"
    stock_item_ids: list[str] = Field(default_factory=list)
    funds: int = Field(default=0, ge=0)
    sell_multiplier: float = Field(default=1.0, ge=0)
    buy_multiplier: float = Field(default=0.5, ge=0)
    price_overrides: dict[str, int] = Field(default_factory=dict)


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
