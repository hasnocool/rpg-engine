"""Core domain models for the headless simulation."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Pydantic base model that rejects unknown fields in engine contracts."""

    model_config = ConfigDict(extra="forbid")


class Ability(StrEnum):
    STRENGTH = "strength"
    DEXTERITY = "dexterity"
    CONSTITUTION = "constitution"
    INTELLIGENCE = "intelligence"
    WISDOM = "wisdom"
    CHARISMA = "charisma"


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


class Health(StrictModel):
    current: int
    maximum: int


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


class Entity(StrictModel):
    id: str
    identity: Identity
    stats: Stats = Field(default_factory=Stats)
    health: Health | None = None
    position: Position = Field(default_factory=Position)
    inventory: Inventory = Field(default_factory=Inventory)
    conditions: set[str] = Field(default_factory=set)
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
    range: int = 5


class WorldState(StrictModel):
    campaign_id: str
    seed: int
    sequence: int = 0
    event_count: int = 0
    time_minutes: int = 0
    rng_counters: dict[str, int] = Field(default_factory=dict)
    entities: dict[str, Entity] = Field(default_factory=dict)
