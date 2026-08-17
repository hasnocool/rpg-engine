"""Ruleset interface. The simulation core depends on this contract, not a game edition."""

from __future__ import annotations

from abc import ABC, abstractmethod

from rpg_engine.models import Ability, ActionBudget, Entity, WeaponSpec
from rpg_engine.resolution import Modifier, ModifierProvenance


class RulesRuntime(ABC):
    @abstractmethod
    def ability_modifier(self, actor: Entity, ability: Ability) -> int: ...

    @abstractmethod
    def check_modifier(self, actor: Entity, ability: Ability) -> int: ...

    @abstractmethod
    def attack_modifier(self, actor: Entity, weapon: WeaponSpec) -> int: ...

    @abstractmethod
    def damage_modifier(self, actor: Entity, weapon: WeaponSpec) -> int: ...

    @abstractmethod
    def armor_class(self, target: Entity) -> int: ...

    def saving_throw_modifier(self, actor: Entity, ability: Ability) -> int:
        return self.ability_modifier(actor, ability)

    def initiative_modifier(self, actor: Entity) -> int:
        return self.ability_modifier(actor, Ability.DEXTERITY)

    def base_action_budget(self, actor: Entity) -> ActionBudget:
        return ActionBudget(movement=actor.stats.movement_speed)

    def check_modifiers(self, actor: Entity, ability: Ability) -> list[Modifier]:
        return [
            Modifier(
                source_id=f"ability:{ability.value}",
                label=f"{ability.value} modifier",
                value=self.check_modifier(actor, ability),
                provenance=ModifierProvenance.ABILITY,
                priority=10,
            )
        ]

    def saving_throw_modifiers(self, actor: Entity, ability: Ability) -> list[Modifier]:
        return [
            Modifier(
                source_id=f"save:{ability.value}",
                label=f"{ability.value} save",
                value=self.saving_throw_modifier(actor, ability),
                provenance=ModifierProvenance.ABILITY,
                priority=10,
            )
        ]

    def initiative_modifiers(self, actor: Entity) -> list[Modifier]:
        return [
            Modifier(
                source_id="initiative:dexterity",
                label="dexterity initiative",
                value=self.initiative_modifier(actor),
                provenance=ModifierProvenance.ABILITY,
                priority=10,
            )
        ]

    def attack_modifiers(self, actor: Entity, weapon: WeaponSpec) -> list[Modifier]:
        return [
            Modifier(
                source_id=f"weapon:{weapon.id}:attack",
                label=f"{weapon.name} attack",
                value=self.attack_modifier(actor, weapon),
                provenance=ModifierProvenance.RULESET,
                priority=20,
            )
        ]
