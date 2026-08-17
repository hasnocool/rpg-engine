"""Typed tactical resolution contexts, outcomes, and modifier provenance."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from rpg_engine.dice import DeterministicRNG
from rpg_engine.models import Ability, StrictModel


class ResolutionKind(StrEnum):
    CHECK = "check"
    ATTACK = "attack"
    SAVING_THROW = "saving_throw"
    INITIATIVE = "initiative"


class ModifierProvenance(StrEnum):
    ABILITY = "ability"
    PROFICIENCY = "proficiency"
    ITEM = "item"
    CONDITION = "condition"
    EFFECT = "effect"
    RULESET = "ruleset"
    HOOK = "hook"


class Modifier(StrictModel):
    """One auditable contribution to a resolution total."""

    source_id: str
    label: str
    value: int
    provenance: ModifierProvenance = ModifierProvenance.RULESET
    priority: int = 100
    stacking_key: str | None = None


class ResolutionContext(StrictModel):
    kind: ResolutionKind
    actor_id: str
    target_id: str | None = None
    ability: Ability | None = None
    dc: int | None = None
    tags: set[str] = Field(default_factory=set)


class ResolutionOutcome(StrictModel):
    context: ResolutionContext
    die_roll: int
    modifiers: list[Modifier] = Field(default_factory=list)
    modifier_total: int
    total: int
    success: bool | None = None


class ModifierPipeline:
    """Deterministically orders and combines modifiers while retaining provenance."""

    @staticmethod
    def normalize(modifiers: list[Modifier]) -> list[Modifier]:
        ordered = sorted(
            modifiers,
            key=lambda modifier: (
                modifier.priority,
                modifier.stacking_key or "",
                modifier.source_id,
                modifier.label,
            ),
        )
        selected: list[Modifier] = []
        keyed: dict[str, Modifier] = {}
        for modifier in ordered:
            if modifier.stacking_key is None:
                selected.append(modifier)
                continue
            current = keyed.get(modifier.stacking_key)
            if current is None or abs(modifier.value) > abs(current.value):
                keyed[modifier.stacking_key] = modifier
        selected.extend(keyed.values())
        return sorted(selected, key=lambda m: (m.priority, m.source_id, m.label))

    def resolve_d20(
        self,
        *,
        context: ResolutionContext,
        modifiers: list[Modifier],
        rng: DeterministicRNG,
        stream: str,
    ) -> ResolutionOutcome:
        applied = self.normalize(modifiers)
        die_roll = rng.roll("1d20", stream=stream).total
        modifier_total = sum(modifier.value for modifier in applied)
        total = die_roll + modifier_total
        success = None if context.dc is None else total >= context.dc
        return ResolutionOutcome(
            context=context,
            die_roll=die_roll,
            modifiers=applied,
            modifier_total=modifier_total,
            total=total,
            success=success,
        )
