"""Core domain models for the headless simulation."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rpg_engine.timeline import TimelineState


class StrictModel(BaseModel):
    """Pydantic base model that rejects unknown fields in engine contracts."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Ability(StrEnum):
    STRENGTH = "strength"
    DEXTERITY = "dexterity"
    CONSTITUTION = "constitution"
    INTELLIGENCE = "intelligence"
    WISDOM = "wisdom"
    CHARISMA = "charisma"


class ActionKind(StrEnum):
    ACTION = "action"
    BONUS_ACTION = "bonus_action"
    REACTION = "reaction"
    MOVEMENT = "movement"


class Identity(StrictModel):
    name: str
    tags: set[str] = Field(default_factory=set)


class Stats(StrictModel):
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10
    proficiency_bonus: int = 2
    armor_class: int = 10
    movement_speed: int = Field(default=30, ge=0)


class Health(StrictModel):
    current: int
    maximum: int

    @model_validator(mode="after")
    def validate_current(self) -> Health:
        if self.maximum < 0:
            raise ValueError("maximum health cannot be negative")
        if not 0 <= self.current <= self.maximum:
            raise ValueError("current health must be between zero and maximum")
        return self


class Position(StrictModel):
    """Presentation-neutral logical position with optional visual coordinates."""

    world: str = "default"
    region: str | None = None
    area: str | None = None
    scene: str | None = None
    zone: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None


class Inventory(StrictModel):
    item_ids: list[str] = Field(default_factory=list)
    equipped_item_ids: list[str] = Field(default_factory=list)


class ResourcePool(StrictModel):
    current: int = Field(ge=0)
    maximum: int = Field(ge=0)
    recharge: Literal["turn", "short_rest", "long_rest", "manual"] = "manual"

    @model_validator(mode="after")
    def validate_current(self) -> ResourcePool:
        if self.current > self.maximum:
            raise ValueError("resource current cannot exceed maximum")
        return self


class DamageProfile(StrictModel):
    resistances: set[str] = Field(default_factory=set)
    immunities: set[str] = Field(default_factory=set)
    vulnerabilities: set[str] = Field(default_factory=set)


class ConcentrationState(StrictModel):
    effect_instance_id: str
    effect_id: str


class Entity(StrictModel):
    id: str
    identity: Identity
    stats: Stats = Field(default_factory=Stats)
    health: Health | None = None
    position: Position = Field(default_factory=Position)
    inventory: Inventory = Field(default_factory=Inventory)
    conditions: set[str] = Field(default_factory=set)
    resources: dict[str, ResourcePool] = Field(default_factory=dict)
    damage_profile: DamageProfile = Field(default_factory=DamageProfile)
    concentration: ConcentrationState | None = None
    faction_id: str | None = None
    ai_profile: str | None = None

    @property
    def is_alive(self) -> bool:
        return self.health is None or self.health.current > 0


class WeaponSpec(StrictModel):
    id: str
    name: str
    ability: Ability = Ability.STRENGTH
    damage: str = "1d4"
    damage_type: str = "bludgeoning"
    attack_bonus: int = 0
    damage_bonus: int = 0
    range: int = Field(default=5, ge=0)


class ActionBudget(StrictModel):
    action: int = Field(default=1, ge=0)
    bonus_action: int = Field(default=1, ge=0)
    reaction: int = Field(default=1, ge=0)
    movement: int = Field(default=30, ge=0)

    def spend(self, kind: ActionKind, amount: int = 1) -> int:
        if amount <= 0:
            raise ValueError("budget spend must be positive")
        field_name = kind.value
        current = int(getattr(self, field_name))
        if current < amount:
            raise ValueError(f"insufficient {kind.value} budget")
        remaining = current - amount
        setattr(self, field_name, remaining)
        return remaining


class InitiativeEntry(StrictModel):
    actor_id: str
    die_roll: int
    modifier: int
    total: int


class EncounterState(StrictModel):
    id: str
    participant_ids: list[str]
    initiative: list[InitiativeEntry]
    round: int = Field(default=1, ge=1)
    turn_index: int = Field(default=0, ge=0)
    active: bool = True
    budgets: dict[str, ActionBudget] = Field(default_factory=dict)

    @property
    def active_actor_id(self) -> str | None:
        if not self.active or not self.initiative:
            return None
        return self.initiative[self.turn_index].actor_id


class ActiveEffect(StrictModel):
    instance_id: str
    effect_id: str
    source_id: str | None = None
    target_id: str
    remaining_turns: int | None = Field(default=None, ge=0)
    expires_on: Literal["start", "end"] = "end"
    concentration: bool = False
    condition_ids: set[str] = Field(default_factory=set)


class ReactionOffer(StrictModel):
    id: str
    trigger_id: str
    actor_id: str
    reaction_id: str
    label: str
    payload: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ReactionWindow(StrictModel):
    trigger_id: str
    kind: str
    source_id: str | None = None
    target_id: str | None = None
    offers: list[ReactionOffer] = Field(default_factory=list)


class WorldState(StrictModel):
    campaign_id: str
    seed: int
    sequence: int = 0
    event_count: int = 0
    time_minutes: int = 0
    timeline: TimelineState = Field(default_factory=TimelineState)
    rng_counters: dict[str, int] = Field(default_factory=dict)
    entities: dict[str, Entity] = Field(default_factory=dict)
    encounters: dict[str, EncounterState] = Field(default_factory=dict)
    active_effects: dict[str, ActiveEffect] = Field(default_factory=dict)
    reaction_windows: dict[str, ReactionWindow] = Field(default_factory=dict)
