"""v0.2 tactical RPG behavior and replay tests."""

from pathlib import Path

import pytest

from rpg_engine.commands import (
    ApplyAreaEffectCommand,
    ApplyEffectCommand,
    AttackTargetCommand,
    CreateEntityCommand,
    EndTurnCommand,
    MoveActorCommand,
    RollSavingThrowCommand,
    StartEncounterCommand,
    UseReactionCommand,
)
from rpg_engine.content.loader import load_content_pack
from rpg_engine.engine import SimulationEngine, SimulationError
from rpg_engine.events import AttackRolledEvent, DamageAppliedEvent, ReactionOfferedEvent
from rpg_engine.hooks import HookRegistry, TriggerContext
from rpg_engine.models import (
    Ability,
    DamageProfile,
    Entity,
    Health,
    Identity,
    Position,
    ReactionOffer,
    ResourcePool,
    Stats,
    WorldState,
)
from rpg_engine.reducer import apply_event

CONTENT = load_content_pack(Path("content/core"))


def actor(
    entity_id: str,
    *,
    hp: int = 100,
    dexterity: int = 10,
    position: Position | None = None,
    damage_profile: DamageProfile | None = None,
) -> Entity:
    return Entity(
        id=entity_id,
        identity=Identity(name=entity_id),
        stats=Stats(strength=16, dexterity=dexterity, armor_class=10, movement_speed=30),
        health=Health(current=hp, maximum=hp),
        position=position or Position(),
        damage_profile=damage_profile or DamageProfile(),
    )


def started_engine(*, hooks: HookRegistry | None = None) -> tuple[SimulationEngine, str, str]:
    engine = SimulationEngine(
        WorldState(campaign_id="tactical", seed=42), content=CONTENT, hooks=hooks
    )
    engine.execute(CreateEntityCommand(entity=actor("alpha", dexterity=16)))
    engine.execute(CreateEntityCommand(entity=actor("beta", dexterity=10)))
    engine.execute(StartEncounterCommand(encounter_id="fight", participant_ids=["alpha", "beta"]))
    encounter = engine.world.encounters["fight"]
    active = encounter.active_actor_id
    assert active is not None
    other = "beta" if active == "alpha" else "alpha"
    return engine, active, other


def test_encounter_initiative_turns_and_action_budget_are_deterministic() -> None:
    first, active, other = started_engine()
    second, active_2, other_2 = started_engine()
    assert first.world.encounters["fight"].initiative == second.world.encounters["fight"].initiative
    assert (active, other) == (active_2, other_2)

    first.execute(AttackTargetCommand(attacker_id=active, target_id=other, weapon_id="longsword"))
    assert first.world.encounters["fight"].budgets[active].action == 0
    with pytest.raises(SimulationError, match="insufficient action"):
        first.execute(
            AttackTargetCommand(
                attacker_id=active, target_id=other, weapon_id="longsword"
            )
        )

    first.execute(EndTurnCommand(actor_id=active, encounter_id="fight"))
    encounter = first.world.encounters["fight"]
    assert encounter.active_actor_id == other
    assert encounter.budgets[other].action == 1


def test_movement_budget_is_authoritative_and_turn_scoped() -> None:
    engine = SimulationEngine(WorldState(campaign_id="move", seed=1), content=CONTENT)
    engine.execute(CreateEntityCommand(entity=actor("a", position=Position(x=0, y=0))))
    engine.execute(CreateEntityCommand(entity=actor("b", position=Position(x=5, y=0))))
    engine.execute(StartEncounterCommand(encounter_id="fight", participant_ids=["a", "b"]))
    active = engine.world.encounters["fight"].active_actor_id
    assert active is not None
    inactive = "b" if active == "a" else "a"

    start = engine.world.entities[active].position
    engine.execute(
        MoveActorCommand(
            actor_id=active,
            position=Position(x=(start.x or 0) + 12, y=start.y or 0),
        )
    )
    assert engine.world.encounters["fight"].budgets[active].movement == 18
    with pytest.raises(SimulationError, match="does not have the active turn"):
        engine.execute(MoveActorCommand(actor_id=inactive, position=Position(x=6, y=0)))


def test_saving_throw_emits_typed_modifier_provenance() -> None:
    engine = SimulationEngine(WorldState(campaign_id="save", seed=5), content=CONTENT)
    engine.execute(CreateEntityCommand(entity=actor("hero", dexterity=16)))
    event = engine.execute(
        RollSavingThrowCommand(actor_id="hero", ability=Ability.DEXTERITY, dc=12)
    )[0]
    assert event.type == "saving_throw_rolled"
    assert event.modifier == 3
    assert event.modifiers[0].source_id == "save:dexterity"
    assert event.total == event.die_roll + event.modifier


def test_damage_resistance_immunity_and_vulnerability_transform_damage() -> None:
    from rpg_engine.content.models import EffectOperation, EffectSpec

    content = CONTENT.model_copy(deep=True)
    content.effects["ten_fire"] = EffectSpec(
        id="ten_fire",
        name="Ten Fire",
        action_cost=None,
        operations=[EffectOperation(type="damage", amount="10", damage_type="fire")],
    )
    engine = SimulationEngine(WorldState(campaign_id="damage", seed=2), content=content)
    engine.execute(CreateEntityCommand(entity=actor("source")))
    profiles = {
        "resistant": DamageProfile(resistances={"fire"}),
        "immune": DamageProfile(immunities={"fire"}),
        "vulnerable": DamageProfile(vulnerabilities={"fire"}),
    }
    expected = {"resistant": (5, 0.5), "immune": (0, 0.0), "vulnerable": (20, 2.0)}
    for target_id, profile in profiles.items():
        engine.execute(CreateEntityCommand(entity=actor(target_id, damage_profile=profile)))
        events = engine.execute(
            ApplyEffectCommand(effect_id="ten_fire", source_id="source", target_id=target_id)
        )
        damage = next(event for event in events if isinstance(event, DamageAppliedEvent))
        assert (damage.amount, damage.multiplier) == expected[target_id]
        assert damage.raw_amount == 10


def test_concentration_resources_and_timed_expiry() -> None:
    from rpg_engine.content.models import EffectOperation, EffectSpec

    content = CONTENT.model_copy(deep=True)
    content.effects["brief_focus"] = EffectSpec(
        id="brief_focus",
        name="Brief Focus",
        action_cost=None,
        duration_turns=1,
        concentration=True,
        resource_costs={"focus": 1},
        operations=[EffectOperation(type="add_condition", condition="focused")],
    )
    engine = SimulationEngine(WorldState(campaign_id="effects", seed=9), content=content)
    focused = actor("focused")
    focused.resources["focus"] = ResourcePool(current=2, maximum=2)
    engine.execute(CreateEntityCommand(entity=focused))
    engine.execute(CreateEntityCommand(entity=actor("other")))

    engine.execute(
        ApplyEffectCommand(
            effect_id="brief_focus", source_id="focused", target_id="focused"
        )
    )
    assert engine.world.entities["focused"].resources["focus"].current == 1
    assert engine.world.entities["focused"].concentration is not None
    assert "focused" in engine.world.entities["focused"].conditions

    engine.execute(
        StartEncounterCommand(
            encounter_id="fight", participant_ids=["focused", "other"]
        )
    )
    active = engine.world.encounters["fight"].active_actor_id
    assert active is not None
    engine.execute(EndTurnCommand(actor_id=active, encounter_id="fight"))
    assert engine.world.entities["focused"].concentration is None
    assert "focused" not in engine.world.entities["focused"].conditions
    assert engine.world.active_effects == {}


def test_area_targeting_is_renderer_neutral_and_deterministic() -> None:
    engine = SimulationEngine(WorldState(campaign_id="area", seed=11), content=CONTENT)
    engine.execute(CreateEntityCommand(entity=actor("caster", position=Position(x=0, y=0))))
    engine.execute(CreateEntityCommand(entity=actor("near", position=Position(x=6, y=0))))
    engine.execute(CreateEntityCommand(entity=actor("far", position=Position(x=20, y=0))))
    events = engine.execute(ApplyAreaEffectCommand(effect_id="fire_burst", source_id="caster"))
    resolved = next(event for event in events if event.type == "area_targets_resolved")
    assert resolved.target_ids == ["near"]
    damaged = [event.target_id for event in events if isinstance(event, DamageAppliedEvent)]
    assert damaged == ["near"]


class OpportunityHook:
    name = "opportunity"

    def triggers_for(self, event: object, world: WorldState):
        if isinstance(event, AttackRolledEvent):
            yield TriggerContext(
                id=f"attack:{event.attacker_id}:{event.target_id}:{world.sequence + 1}",
                kind="after_attack",
                source_id=event.attacker_id,
                target_id=event.target_id,
            )

    def reactions_for(self, trigger: TriggerContext, world: WorldState):
        if trigger.target_id is not None:
            yield ReactionOffer(
                id=f"offer:{trigger.id}:{trigger.target_id}",
                trigger_id=trigger.id,
                actor_id=trigger.target_id,
                reaction_id="counter",
                label="Counter",
            )


def test_trigger_hook_opens_reaction_window_and_reaction_spends_budget() -> None:
    engine, active, other = started_engine(hooks=HookRegistry([OpportunityHook()]))
    events = engine.execute(
        AttackTargetCommand(attacker_id=active, target_id=other, weapon_id="longsword")
    )
    offered = next(event for event in events if isinstance(event, ReactionOfferedEvent))
    assert offered.offer.actor_id == other
    engine.execute(
        UseReactionCommand(
            actor_id=other,
            trigger_id=offered.offer.trigger_id,
            reaction_id="counter",
        )
    )
    assert engine.world.encounters["fight"].budgets[other].reaction == 0


def test_tactical_event_replay_reconstructs_world_exactly() -> None:
    original = SimulationEngine(WorldState(campaign_id="replay", seed=2026), content=CONTENT)
    all_events = []
    all_events += original.execute(CreateEntityCommand(entity=actor("a", hp=200, dexterity=16)))
    all_events += original.execute(CreateEntityCommand(entity=actor("b", hp=200, dexterity=10)))
    all_events += original.execute(
        StartEncounterCommand(encounter_id="fight", participant_ids=["a", "b"])
    )
    active = original.world.encounters["fight"].active_actor_id
    assert active is not None
    other = "b" if active == "a" else "a"
    all_events += original.execute(
        AttackTargetCommand(attacker_id=active, target_id=other, weapon_id="longsword")
    )
    all_events += original.execute(EndTurnCommand(actor_id=active, encounter_id="fight"))

    replayed = WorldState(campaign_id="replay", seed=2026)
    for event in all_events:
        apply_event(replayed, event)
    assert replayed == original.world
