"""Authoritative, presentation-agnostic simulation command processor."""

from __future__ import annotations

from rpg_engine.commands import (
    AdvanceTimeCommand,
    ApplyEffectCommand,
    AttackTargetCommand,
    Command,
    CreateEntityCommand,
    EndTurnCommand,
    MoveActorCommand,
    RollCheckCommand,
)
from rpg_engine.content.models import ContentRegistry
from rpg_engine.dice import DeterministicRNG
from rpg_engine.effects import EffectPipeline
from rpg_engine.events import (
    ActorDefeatedEvent,
    ActorMovedEvent,
    AttackRolledEvent,
    CheckRolledEvent,
    DamageAppliedEvent,
    EntityCreatedEvent,
    Event,
    EventBase,
    TimeAdvancedEvent,
    TurnEndedEvent,
)
from rpg_engine.models import Entity, WorldState
from rpg_engine.rules.base import RulesRuntime
from rpg_engine.rules.d20 import D20RulesRuntime


class SimulationError(ValueError):
    """Rejected command or invalid simulation state."""


class SimulationEngine:
    def __init__(
        self,
        world: WorldState,
        *,
        rules: RulesRuntime | None = None,
        content: ContentRegistry | None = None,
    ) -> None:
        self.world = world
        self.rules = rules or D20RulesRuntime()
        self.content = content or ContentRegistry.with_core_defaults()
        self.rng = DeterministicRNG(world.seed, world.rng_counters)
        self.effects = EffectPipeline()

    def _entity(self, entity_id: str) -> Entity:
        try:
            return self.world.entities[entity_id]
        except KeyError as exc:
            raise SimulationError(f"unknown entity: {entity_id}") from exc

    def _stamp(self, events: list[EventBase]) -> list[Event]:
        stamped: list[Event] = []
        for event in events:
            self.world.sequence += 1
            self.world.event_count += 1
            stamped_event = event.model_copy(
                update={
                    "sequence": self.world.sequence,
                    "campaign_id": self.world.campaign_id,
                    "rng_counters_after": dict(self.world.rng_counters),
                }
            )
            stamped.append(stamped_event)  # type: ignore[arg-type]
        return stamped

    def execute(self, command: Command) -> list[Event]:
        raw_events: list[EventBase]
        if isinstance(command, CreateEntityCommand):
            if command.entity.id in self.world.entities:
                raise SimulationError(f"entity already exists: {command.entity.id}")
            entity = command.entity.model_copy(deep=True)
            self.world.entities[entity.id] = entity
            raw_events = [EntityCreatedEvent(entity=entity.model_copy(deep=True))]

        elif isinstance(command, MoveActorCommand):
            actor = self._entity(command.actor_id)
            if not actor.is_alive:
                raise SimulationError("defeated actors cannot move")
            actor.position = command.position.model_copy(deep=True)
            raw_events = [
                ActorMovedEvent(
                    actor_id=actor.id, position=actor.position.model_copy(deep=True)
                )
            ]

        elif isinstance(command, RollCheckCommand):
            actor = self._entity(command.actor_id)
            modifier = self.rules.check_modifier(actor, command.ability)
            stream = command.stream or f"check:{actor.id}:{command.ability.value}"
            roll = self.rng.roll("1d20", stream=stream)
            total = roll.total + modifier
            raw_events = [
                CheckRolledEvent(
                    actor_id=actor.id,
                    ability=command.ability,
                    dc=command.dc,
                    die_roll=roll.total,
                    modifier=modifier,
                    total=total,
                    success=total >= command.dc,
                )
            ]

        elif isinstance(command, AttackTargetCommand):
            attacker = self._entity(command.attacker_id)
            target = self._entity(command.target_id)
            if not attacker.is_alive:
                raise SimulationError("defeated actors cannot attack")
            if not target.is_alive:
                raise SimulationError("target is already defeated")
            try:
                weapon = self.content.weapons[command.weapon_id]
            except KeyError as exc:
                raise SimulationError(f"unknown weapon: {command.weapon_id}") from exc
            modifier = self.rules.attack_modifier(attacker, weapon)
            armor_class = self.rules.armor_class(target)
            roll = self.rng.roll(
                "1d20", stream=f"combat:attack:{attacker.id}:{target.id}:{weapon.id}"
            )
            total = roll.total + modifier
            hit = total >= armor_class
            raw_events = [
                AttackRolledEvent(
                    attacker_id=attacker.id,
                    target_id=target.id,
                    weapon_id=weapon.id,
                    die_roll=roll.total,
                    modifier=modifier,
                    total=total,
                    armor_class=armor_class,
                    hit=hit,
                )
            ]
            if hit:
                if target.health is None:
                    raise SimulationError(f"target {target.id!r} has no health component")
                damage_roll = self.rng.roll(
                    weapon.damage,
                    stream=f"combat:damage:{attacker.id}:{target.id}:{weapon.id}",
                )
                damage = max(
                    0,
                    damage_roll.total + self.rules.damage_modifier(attacker, weapon),
                )
                target.health.current = max(0, target.health.current - damage)
                raw_events.append(
                    DamageAppliedEvent(
                        source_id=attacker.id,
                        target_id=target.id,
                        damage_type=weapon.damage_type,
                        amount=damage,
                        hp_after=target.health.current,
                    )
                )
                if target.health.current == 0:
                    raw_events.append(
                        ActorDefeatedEvent(actor_id=target.id, source_id=attacker.id)
                    )

        elif isinstance(command, ApplyEffectCommand):
            target = self._entity(command.target_id)
            source = self._entity(command.source_id) if command.source_id else None
            try:
                effect = self.content.effects[command.effect_id]
            except KeyError as exc:
                raise SimulationError(f"unknown effect: {command.effect_id}") from exc
            raw_events = list(
                self.effects.apply(effect, target=target, source=source, rng=self.rng)
            )

        elif isinstance(command, AdvanceTimeCommand):
            self.world.time_minutes += command.minutes
            raw_events = [
                TimeAdvancedEvent(minutes=command.minutes, time_minutes=self.world.time_minutes)
            ]

        elif isinstance(command, EndTurnCommand):
            self._entity(command.actor_id)
            raw_events = [TurnEndedEvent(actor_id=command.actor_id)]

        else:
            raise SimulationError(f"unsupported command: {type(command).__name__}")

        return self._stamp(raw_events)
