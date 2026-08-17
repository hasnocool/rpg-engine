"""Ruleset interface. The simulation core depends on this contract, not a game edition."""

from __future__ import annotations

from abc import ABC, abstractmethod

from rpg_engine.models import Ability, Entity, WeaponSpec


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
