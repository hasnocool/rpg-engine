"""Authoritative, presentation-agnostic tactical simulation command processor."""

from __future__ import annotations

from rpg_engine.adventure import AdventureError, AdventureRuntime
from rpg_engine.commands import (
    AdvanceTimeCommand,
    ApplyAreaEffectCommand,
    ApplyEffectCommand,
    AttackTargetCommand,
    Command,
    CreateEntityCommand,
    EndEncounterCommand,
    EndTurnCommand,
    MoveActorCommand,
    RollCheckCommand,
    RollSavingThrowCommand,
    StartEncounterCommand,
    UseReactionCommand,
)
from rpg_engine.content.models import ContentRegistry, EffectSpec
from rpg_engine.dice import DeterministicRNG
from rpg_engine.effects import EffectPipeline
from rpg_engine.events import (
    ActionBudgetSpentEvent,
    ActorDefeatedEvent,
    ActorMovedEvent,
    AreaTargetsResolvedEvent,
    AttackRolledEvent,
    CheckRolledEvent,
    ConcentrationEndedEvent,
    ConcentrationStartedEvent,
    ConditionRemovedEvent,
    DamageAppliedEvent,
    EffectActivatedEvent,
    EffectDurationTickedEvent,
    EffectExpiredEvent,
    EncounterEndedEvent,
    EncounterStartedEvent,
    EntityCreatedEvent,
    Event,
    EventBase,
    InitiativeRolledEvent,
    ReactionOfferedEvent,
    ReactionUsedEvent,
    ResourceSpentEvent,
    SavingThrowRolledEvent,
    TimeAdvancedEvent,
    TriggerRaisedEvent,
    TurnEndedEvent,
    TurnStartedEvent,
)
from rpg_engine.hooks import HookRegistry
from rpg_engine.models import (
    ActionKind,
    ActiveEffect,
    ConcentrationState,
    EncounterState,
    Entity,
    InitiativeEntry,
    ReactionWindow,
    WorldState,
)
from rpg_engine.resolution import ModifierPipeline, ResolutionContext, ResolutionKind
from rpg_engine.rules.base import RulesRuntime
from rpg_engine.rules.d20 import D20RulesRuntime
from rpg_engine.spatial import GridSpatialAdapter, SpatialAdapter, TargetingContract, TargetShape


class SimulationError(ValueError):
    """Rejected command or invalid simulation state."""


class SimulationEngine:
    def __init__(
        self,
        world: WorldState,
        *,
        rules: RulesRuntime | None = None,
        content: ContentRegistry | None = None,
        spatial: SpatialAdapter | None = None,
        hooks: HookRegistry | None = None,
    ) -> None:
        self.world = world
        self.rules = rules or D20RulesRuntime()
        self.content = content or ContentRegistry.with_core_defaults()
        self.spatial = spatial or GridSpatialAdapter()
        self.hooks = hooks or HookRegistry()
        self.rng = DeterministicRNG(world.seed, world.rng_counters)
        self.effects = EffectPipeline()
        self.modifiers = ModifierPipeline()
        self.adventure = AdventureRuntime(
            world, content=self.content, rules=self.rules, rng=self.rng
        )

    def _entity(self, entity_id: str) -> Entity:
        try:
            return self.world.entities[entity_id]
        except KeyError as exc:
            raise SimulationError(f"unknown entity: {entity_id}") from exc

    def _encounter(self, encounter_id: str) -> EncounterState:
        try:
            encounter = self.world.encounters[encounter_id]
        except KeyError as exc:
            raise SimulationError(f"unknown encounter: {encounter_id}") from exc
        if not encounter.active:
            raise SimulationError(f"encounter is not active: {encounter_id}")
        return encounter

    def _active_encounter_for_actor(self, actor_id: str) -> EncounterState | None:
        matches = [
            encounter
            for encounter in self.world.encounters.values()
            if encounter.active and actor_id in encounter.participant_ids
        ]
        if len(matches) > 1:
            raise SimulationError(f"actor {actor_id!r} belongs to multiple active encounters")
        return matches[0] if matches else None

    def _spend_budget(
        self,
        actor_id: str,
        kind: ActionKind,
        *,
        amount: int = 1,
    ) -> list[EventBase]:
        encounter = self._active_encounter_for_actor(actor_id)
        if encounter is None:
            return []
        if kind != ActionKind.REACTION and encounter.active_actor_id != actor_id:
            raise SimulationError(f"actor {actor_id!r} does not have the active turn")
        budget = encounter.budgets[actor_id]
        try:
            remaining = budget.spend(kind, amount)
        except ValueError as exc:
            raise SimulationError(str(exc)) from exc
        return [
            ActionBudgetSpentEvent(
                encounter_id=encounter.id,
                actor_id=actor_id,
                budget_kind=kind.value,
                amount=amount,
                remaining=remaining,
            )
        ]

    def _damage_events(
        self,
        target: Entity,
        source: Entity | None,
        damage_type: str,
        raw_amount: int,
    ) -> list[EventBase]:
        if target.health is None:
            raise SimulationError(f"target {target.id!r} has no health component")
        profile = target.damage_profile
        if damage_type in profile.immunities:
            multiplier = 0.0
        else:
            resistant = damage_type in profile.resistances
            vulnerable = damage_type in profile.vulnerabilities
            if resistant and vulnerable:
                multiplier = 1.0
            elif resistant:
                multiplier = 0.5
            elif vulnerable:
                multiplier = 2.0
            else:
                multiplier = 1.0
        amount = max(0, int(raw_amount * multiplier))
        target.health.current = max(0, target.health.current - amount)
        events: list[EventBase] = [
            DamageAppliedEvent(
                source_id=source.id if source else None,
                target_id=target.id,
                damage_type=damage_type,
                raw_amount=raw_amount,
                multiplier=multiplier,
                amount=amount,
                hp_after=target.health.current,
            )
        ]
        if target.health.current == 0:
            events.append(
                ActorDefeatedEvent(
                    actor_id=target.id,
                    source_id=source.id if source else None,
                )
            )
        return events

    def _spend_effect_resources(
        self, effect: EffectSpec, source: Entity | None
    ) -> list[EventBase]:
        if not effect.resource_costs:
            return []
        if source is None:
            raise SimulationError(f"effect {effect.id!r} requires a source with resources")
        for resource_id, cost in effect.resource_costs.items():
            pool = source.resources.get(resource_id)
            if pool is None or pool.current < cost:
                raise SimulationError(f"insufficient resource {resource_id!r}")
        events: list[EventBase] = []
        for resource_id, cost in sorted(effect.resource_costs.items()):
            pool = source.resources[resource_id]
            pool.current -= cost
            events.append(
                ResourceSpentEvent(
                    actor_id=source.id,
                    resource_id=resource_id,
                    amount=cost,
                    remaining=pool.current,
                )
            )
        return events

    def _condition_still_active(self, target_id: str, condition: str, excluding: str) -> bool:
        return any(
            effect.instance_id != excluding
            and effect.target_id == target_id
            and condition in effect.condition_ids
            for effect in self.world.active_effects.values()
        )

    def _expire_effect(self, instance_id: str, *, reason: str) -> list[EventBase]:
        effect = self.world.active_effects.pop(instance_id, None)
        if effect is None:
            return []
        events: list[EventBase] = []
        target = self._entity(effect.target_id)
        for condition in sorted(effect.condition_ids):
            if not self._condition_still_active(target.id, condition, excluding=instance_id):
                target.conditions.discard(condition)
                events.append(ConditionRemovedEvent(target_id=target.id, condition=condition))
        if effect.concentration and effect.source_id:
            source = self._entity(effect.source_id)
            if source.concentration and source.concentration.effect_instance_id == instance_id:
                source.concentration = None
                events.append(
                    ConcentrationEndedEvent(
                        actor_id=source.id,
                        effect_instance_id=instance_id,
                        effect_id=effect.effect_id,
                        reason=reason,
                    )
                )
        events.append(
            EffectExpiredEvent(
                effect_instance_id=instance_id,
                effect_id=effect.effect_id,
                target_id=effect.target_id,
            )
        )
        return events

    def _tick_effects(self, phase: str) -> list[EventBase]:
        events: list[EventBase] = []
        for instance_id in sorted(list(self.world.active_effects)):
            effect = self.world.active_effects.get(instance_id)
            if effect is None or effect.remaining_turns is None or effect.expires_on != phase:
                continue
            effect.remaining_turns -= 1
            if effect.remaining_turns <= 0:
                events.extend(self._expire_effect(instance_id, reason="duration_expired"))
            else:
                events.append(
                    EffectDurationTickedEvent(
                        effect_instance_id=instance_id,
                        remaining_turns=effect.remaining_turns,
                    )
                )
        return events

    def _activate_effect(
        self, effect: EffectSpec, target: Entity, source: Entity | None
    ) -> list[EventBase]:
        if effect.duration_turns is None and not effect.concentration:
            return []
        instance_id = f"{effect.id}@{self.world.sequence + 1}:{target.id}"
        active = ActiveEffect(
            instance_id=instance_id,
            effect_id=effect.id,
            source_id=source.id if source else None,
            target_id=target.id,
            remaining_turns=effect.duration_turns,
            expires_on=effect.expires_on,
            concentration=effect.concentration,
            condition_ids={
                operation.condition
                for operation in effect.operations
                if operation.type == "add_condition" and operation.condition
            },
        )
        events: list[EventBase] = []
        if effect.concentration:
            if source is None:
                raise SimulationError("concentration effects require a source")
            source.concentration = ConcentrationState(
                effect_instance_id=instance_id,
                effect_id=effect.id,
            )
        self.world.active_effects[instance_id] = active
        events.append(EffectActivatedEvent(effect=active.model_copy(deep=True)))
        if effect.concentration and source is not None:
            events.append(
                ConcentrationStartedEvent(
                    actor_id=source.id,
                    effect_instance_id=instance_id,
                    effect_id=effect.id,
                )
            )
        return events

    def _prepare_effect(
        self, effect: EffectSpec, source: Entity | None
    ) -> list[EventBase]:
        events: list[EventBase] = []
        if source is not None and effect.action_cost is not None:
            events.extend(self._spend_budget(source.id, effect.action_cost))
        events.extend(self._spend_effect_resources(effect, source))
        if effect.concentration:
            if source is None:
                raise SimulationError("concentration effects require a source")
            if source.concentration is not None:
                events.extend(
                    self._expire_effect(
                        source.concentration.effect_instance_id,
                        reason="concentration_replaced",
                    )
                )
        return events

    def _apply_effect_to_target(
        self, effect: EffectSpec, target: Entity, source: Entity | None
    ) -> list[EventBase]:
        events = list(
            self.effects.apply(
                effect,
                target=target,
                source=source,
                rng=self.rng,
                damage_resolver=self._damage_events,
            )
        )
        events.extend(self._activate_effect(effect, target, source))
        return events

    def _expand_hooks(self, events: list[EventBase]) -> list[EventBase]:
        expanded = list(events)
        for event in events:
            for trigger, offers in self.hooks.collect(event, self.world):
                valid_offers = []
                for offer in offers:
                    encounter = self._active_encounter_for_actor(offer.actor_id)
                    if encounter is None:
                        continue
                    if encounter.budgets[offer.actor_id].reaction <= 0:
                        continue
                    valid_offers.append(offer)
                self.world.reaction_windows[trigger.id] = ReactionWindow(
                    trigger_id=trigger.id,
                    kind=trigger.kind,
                    source_id=trigger.source_id,
                    target_id=trigger.target_id,
                    offers=valid_offers,
                )
                expanded.append(
                    TriggerRaisedEvent(
                        trigger_id=trigger.id,
                        kind=trigger.kind,
                        source_id=trigger.source_id,
                        target_id=trigger.target_id,
                    )
                )
                expanded.extend(ReactionOfferedEvent(offer=offer) for offer in valid_offers)
        return expanded

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

        elif isinstance(command, StartEncounterCommand):
            if (
                command.encounter_id in self.world.encounters
                and self.world.encounters[command.encounter_id].active
            ):
                raise SimulationError(f"encounter already active: {command.encounter_id}")
            participant_ids = list(dict.fromkeys(command.participant_ids))
            if len(participant_ids) != len(command.participant_ids):
                raise SimulationError("encounter participants must be unique")
            raw_events = []
            entries: list[InitiativeEntry] = []
            for actor_id in participant_ids:
                actor = self._entity(actor_id)
                if not actor.is_alive:
                    raise SimulationError("defeated actors cannot enter an encounter")
                if self._active_encounter_for_actor(actor_id) is not None:
                    raise SimulationError(
                        f"actor already belongs to an active encounter: {actor_id}"
                    )
                outcome = self.modifiers.resolve_d20(
                    context=ResolutionContext(
                        kind=ResolutionKind.INITIATIVE,
                        actor_id=actor.id,
                    ),
                    modifiers=self.rules.initiative_modifiers(actor),
                    rng=self.rng,
                    stream=f"combat:initiative:{command.encounter_id}:{actor.id}",
                )
                entries.append(
                    InitiativeEntry(
                        actor_id=actor.id,
                        die_roll=outcome.die_roll,
                        modifier=outcome.modifier_total,
                        total=outcome.total,
                    )
                )
                raw_events.append(
                    InitiativeRolledEvent(
                        encounter_id=command.encounter_id,
                        actor_id=actor.id,
                        die_roll=outcome.die_roll,
                        modifier=outcome.modifier_total,
                        modifiers=outcome.modifiers,
                        total=outcome.total,
                    )
                )
            entries.sort(key=lambda item: (-item.total, -item.modifier, item.actor_id))
            encounter = EncounterState(
                id=command.encounter_id,
                participant_ids=participant_ids,
                initiative=entries,
                budgets={
                    actor_id: self.rules.base_action_budget(self._entity(actor_id))
                    for actor_id in participant_ids
                },
            )
            self.world.encounters[encounter.id] = encounter
            raw_events.append(EncounterStartedEvent(encounter=encounter.model_copy(deep=True)))
            active_id = encounter.active_actor_id
            assert active_id is not None
            raw_events.extend(self._tick_effects("start"))
            raw_events.append(
                TurnStartedEvent(
                    encounter_id=encounter.id,
                    actor_id=active_id,
                    round=encounter.round,
                    turn_index=encounter.turn_index,
                    budget=encounter.budgets[active_id].model_copy(deep=True),
                )
            )

        elif isinstance(command, EndEncounterCommand):
            encounter = self._encounter(command.encounter_id)
            encounter.active = False
            self.world.reaction_windows = {
                trigger_id: window
                for trigger_id, window in self.world.reaction_windows.items()
                if not any(offer.actor_id in encounter.participant_ids for offer in window.offers)
            }
            raw_events = [
                EncounterEndedEvent(
                    encounter_id=encounter.id,
                    participant_ids=list(encounter.participant_ids),
                )
            ]

        elif isinstance(command, MoveActorCommand):
            actor = self._entity(command.actor_id)
            if not actor.is_alive:
                raise SimulationError("defeated actors cannot move")
            raw_events = []
            encounter = self._active_encounter_for_actor(actor.id)
            if encounter is not None:
                try:
                    cost = self.spatial.movement_cost(actor.position, command.position)
                except ValueError as exc:
                    raise SimulationError(str(exc)) from exc
                raw_events.extend(self._spend_budget(actor.id, ActionKind.MOVEMENT, amount=cost))
            actor.position = command.position.model_copy(deep=True)
            raw_events.append(
                ActorMovedEvent(
                    actor_id=actor.id,
                    position=actor.position.model_copy(deep=True),
                )
            )

        elif isinstance(command, RollCheckCommand):
            actor = self._entity(command.actor_id)
            outcome = self.modifiers.resolve_d20(
                context=ResolutionContext(
                    kind=ResolutionKind.CHECK,
                    actor_id=actor.id,
                    ability=command.ability,
                    dc=command.dc,
                ),
                modifiers=self.rules.check_modifiers(actor, command.ability),
                rng=self.rng,
                stream=command.stream or f"check:{actor.id}:{command.ability.value}",
            )
            raw_events = [
                CheckRolledEvent(
                    actor_id=actor.id,
                    ability=command.ability,
                    dc=command.dc,
                    die_roll=outcome.die_roll,
                    modifier=outcome.modifier_total,
                    modifiers=outcome.modifiers,
                    total=outcome.total,
                    success=bool(outcome.success),
                )
            ]

        elif isinstance(command, RollSavingThrowCommand):
            actor = self._entity(command.actor_id)
            outcome = self.modifiers.resolve_d20(
                context=ResolutionContext(
                    kind=ResolutionKind.SAVING_THROW,
                    actor_id=actor.id,
                    target_id=command.source_id,
                    ability=command.ability,
                    dc=command.dc,
                ),
                modifiers=self.rules.saving_throw_modifiers(actor, command.ability),
                rng=self.rng,
                stream=command.stream or f"save:{actor.id}:{command.ability.value}",
            )
            raw_events = [
                SavingThrowRolledEvent(
                    actor_id=actor.id,
                    source_id=command.source_id,
                    ability=command.ability,
                    dc=command.dc,
                    die_roll=outcome.die_roll,
                    modifier=outcome.modifier_total,
                    modifiers=outcome.modifiers,
                    total=outcome.total,
                    success=bool(outcome.success),
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
            if not self.spatial.can_target(
                attacker.position,
                target.position,
                TargetingContract(max_range=weapon.range),
            ):
                raise SimulationError("target is out of weapon range")
            raw_events = self._spend_budget(attacker.id, ActionKind.ACTION)
            armor_class = self.rules.armor_class(target)
            outcome = self.modifiers.resolve_d20(
                context=ResolutionContext(
                    kind=ResolutionKind.ATTACK,
                    actor_id=attacker.id,
                    target_id=target.id,
                    dc=armor_class,
                    tags={f"weapon:{weapon.id}"},
                ),
                modifiers=self.rules.attack_modifiers(attacker, weapon),
                rng=self.rng,
                stream=f"combat:attack:{attacker.id}:{target.id}:{weapon.id}",
            )
            hit = bool(outcome.success)
            raw_events.append(
                AttackRolledEvent(
                    attacker_id=attacker.id,
                    target_id=target.id,
                    weapon_id=weapon.id,
                    die_roll=outcome.die_roll,
                    modifier=outcome.modifier_total,
                    modifiers=outcome.modifiers,
                    total=outcome.total,
                    armor_class=armor_class,
                    hit=hit,
                )
            )
            if hit:
                damage_roll = self.rng.roll(
                    weapon.damage,
                    stream=f"combat:damage:{attacker.id}:{target.id}:{weapon.id}",
                )
                raw_amount = max(
                    0,
                    damage_roll.total + self.rules.damage_modifier(attacker, weapon),
                )
                raw_events.extend(
                    self._damage_events(target, attacker, weapon.damage_type, raw_amount)
                )

        elif isinstance(command, ApplyEffectCommand):
            target = self._entity(command.target_id)
            source = self._entity(command.source_id) if command.source_id else None
            try:
                effect = self.content.effects[command.effect_id]
            except KeyError as exc:
                raise SimulationError(f"unknown effect: {command.effect_id}") from exc
            if source is not None and not self.spatial.can_target(
                source.position, target.position, effect.targeting
            ):
                raise SimulationError("effect target is out of range")
            raw_events = self._prepare_effect(effect, source)
            raw_events.extend(self._apply_effect_to_target(effect, target, source))

        elif isinstance(command, ApplyAreaEffectCommand):
            try:
                effect = self.content.effects[command.effect_id]
            except KeyError as exc:
                raise SimulationError(f"unknown effect: {command.effect_id}") from exc
            if effect.targeting.shape == TargetShape.SINGLE:
                raise SimulationError(
                    "area-effect command requires a non-single targeting contract"
                )
            if effect.concentration:
                raise SimulationError(
                    "concentration area effects require a ruleset-specific handler"
                )
            source = self._entity(command.source_id) if command.source_id else None
            origin = command.origin or (source.position if source else None)
            if origin is None:
                raise SimulationError("area effect requires an origin or source")
            candidates = (
                [self._entity(entity_id) for entity_id in command.candidate_ids]
                if command.candidate_ids is not None
                else list(self.world.entities.values())
            )
            selected_ids = self.spatial.targets_in_area(origin, candidates, effect.targeting)
            if source is not None and not effect.targeting.include_source:
                selected_ids = [entity_id for entity_id in selected_ids if entity_id != source.id]
            raw_events = self._prepare_effect(effect, source)
            raw_events.append(
                AreaTargetsResolvedEvent(
                    effect_id=effect.id,
                    source_id=source.id if source else None,
                    target_ids=selected_ids,
                )
            )
            for target_id in selected_ids:
                raw_events.extend(
                    self._apply_effect_to_target(effect, self._entity(target_id), source)
                )

        elif isinstance(command, AdvanceTimeCommand):
            self.world.time_minutes += command.minutes
            raw_events = [
                TimeAdvancedEvent(
                    minutes=command.minutes,
                    time_minutes=self.world.time_minutes,
                )
            ]

        elif isinstance(command, EndTurnCommand):
            self._entity(command.actor_id)
            encounter = (
                self._encounter(command.encounter_id)
                if command.encounter_id
                else self._active_encounter_for_actor(command.actor_id)
            )
            if encounter is None:
                raw_events = [TurnEndedEvent(actor_id=command.actor_id)]
            else:
                if encounter.active_actor_id != command.actor_id:
                    raise SimulationError("only the active actor can end the turn")
                raw_events = [
                    TurnEndedEvent(
                        actor_id=command.actor_id,
                        encounter_id=encounter.id,
                        round=encounter.round,
                    )
                ]
                raw_events.extend(self._tick_effects("end"))
                encounter.turn_index += 1
                if encounter.turn_index >= len(encounter.initiative):
                    encounter.turn_index = 0
                    encounter.round += 1
                next_actor_id = encounter.active_actor_id
                assert next_actor_id is not None
                encounter.budgets[next_actor_id] = self.rules.base_action_budget(
                    self._entity(next_actor_id)
                )
                raw_events[0] = raw_events[0].model_copy(update={"next_actor_id": next_actor_id})
                raw_events.extend(self._tick_effects("start"))
                raw_events.append(
                    TurnStartedEvent(
                        encounter_id=encounter.id,
                        actor_id=next_actor_id,
                        round=encounter.round,
                        turn_index=encounter.turn_index,
                        budget=encounter.budgets[next_actor_id].model_copy(deep=True),
                    )
                )

        elif isinstance(command, UseReactionCommand):
            window = self.world.reaction_windows.get(command.trigger_id)
            if window is None:
                raise SimulationError(f"unknown reaction trigger: {command.trigger_id}")
            offer = next(
                (
                    candidate
                    for candidate in window.offers
                    if candidate.actor_id == command.actor_id
                    and candidate.reaction_id == command.reaction_id
                ),
                None,
            )
            if offer is None:
                raise SimulationError("reaction is not offered to this actor")
            raw_events = self._spend_budget(command.actor_id, ActionKind.REACTION)
            window.offers = [candidate for candidate in window.offers if candidate.id != offer.id]
            if not window.offers:
                self.world.reaction_windows.pop(command.trigger_id, None)
            raw_events.append(
                ReactionUsedEvent(
                    trigger_id=command.trigger_id,
                    actor_id=command.actor_id,
                    reaction_id=command.reaction_id,
                )
            )

        elif self.adventure.handles(command):
            try:
                raw_events = self.adventure.execute(command)
            except AdventureError as exc:
                raise SimulationError(str(exc)) from exc

        else:
            raise SimulationError(f"unsupported command: {type(command).__name__}")

        return self._stamp(self._expand_hooks(raw_events))
