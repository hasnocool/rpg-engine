"""Validated content-pack models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from rpg_engine.models import StrictModel, WeaponSpec


class EffectOperation(StrictModel):
    type: Literal["damage", "heal", "add_condition", "remove_condition"]
    amount: str | None = None
    damage_type: str = "untyped"
    condition: str | None = None


class EffectSpec(StrictModel):
    id: str
    name: str
    operations: list[EffectOperation] = Field(default_factory=list)


class ContentManifest(StrictModel):
    id: str
    name: str
    version: str
    ruleset: str = "d20"


class ContentRegistry(StrictModel):
    manifest: ContentManifest | None = None
    weapons: dict[str, WeaponSpec] = Field(default_factory=dict)
    effects: dict[str, EffectSpec] = Field(default_factory=dict)

    @classmethod
    def with_core_defaults(cls) -> "ContentRegistry":
        return cls(
            weapons={
                "unarmed": WeaponSpec(
                    id="unarmed",
                    name="Unarmed Strike",
                    damage="1d1",
                    damage_type="bludgeoning",
                )
            }
        )
