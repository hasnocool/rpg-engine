"""Generic d20-style ruleset with no proprietary game content."""

from __future__ import annotations

from rpg_engine.models import Ability, Entity, WeaponSpec
from rpg_engine.rules.base import RulesRuntime


class D20RulesRuntime(RulesRuntime):
    def ability_modifier(self, actor: Entity, ability: Ability) -> int:
        score = int(getattr(actor.stats, ability.value))
        return (score - 10) // 2

    def check_modifier(self, actor: Entity, ability: Ability) -> int:
        return self.ability_modifier(actor, ability)

    def attack_modifier(self, actor: Entity, weapon: WeaponSpec) -> int:
        return (
            self.ability_modifier(actor, weapon.ability)
            + actor.stats.proficiency_bonus
            + weapon.attack_bonus
        )

    def damage_modifier(self, actor: Entity, weapon: WeaponSpec) -> int:
        return self.ability_modifier(actor, weapon.ability) + weapon.damage_bonus

    def armor_class(self, target: Entity) -> int:
        return target.stats.armor_class
