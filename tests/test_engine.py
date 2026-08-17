"""Command/event engine tests."""

from pathlib import Path

from rpg_engine.commands import (
    ApplyEffectCommand,
    AttackTargetCommand,
    CreateEntityCommand,
    RollCheckCommand,
)
from rpg_engine.content.loader import load_content_pack
from rpg_engine.engine import SimulationEngine
from rpg_engine.events import AttackRolledEvent, DamageAppliedEvent
from rpg_engine.models import Ability, Entity, Health, Identity, Stats, WorldState


def _actor(entity_id: str, *, hp: int = 20, armor_class: int = 10) -> Entity:
    return Entity(
        id=entity_id,
        identity=Identity(name=entity_id),
        stats=Stats(strength=16, dexterity=14, armor_class=armor_class),
        health=Health(current=hp, maximum=hp),
    )


def test_attack_is_deterministic_for_same_world_and_commands() -> None:
    content = load_content_pack(Path("content/core"))

    def run() -> tuple[list[object], WorldState]:
        engine = SimulationEngine(WorldState(campaign_id="c1", seed=99), content=content)
        engine.execute(CreateEntityCommand(entity=_actor("hero")))
        engine.execute(CreateEntityCommand(entity=_actor("target", armor_class=11)))
        events = engine.execute(
            AttackTargetCommand(attacker_id="hero", target_id="target", weapon_id="longsword")
        )
        return [event.model_dump(mode="json") for event in events], engine.world

    events_a, world_a = run()
    events_b, world_b = run()
    assert events_a == events_b
    assert world_a == world_b
    assert isinstance(events_a, list)


def test_attack_emits_roll_and_optional_damage() -> None:
    content = load_content_pack(Path("content/core"))
    engine = SimulationEngine(WorldState(campaign_id="c1", seed=5), content=content)
    engine.execute(CreateEntityCommand(entity=_actor("hero")))
    engine.execute(CreateEntityCommand(entity=_actor("target", armor_class=1)))

    events = engine.execute(
        AttackTargetCommand(attacker_id="hero", target_id="target", weapon_id="longsword")
    )

    assert isinstance(events[0], AttackRolledEvent)
    assert events[0].hit is True
    assert any(isinstance(event, DamageAppliedEvent) for event in events)


def test_check_and_effect_pipeline() -> None:
    content = load_content_pack(Path("content/core"))
    engine = SimulationEngine(WorldState(campaign_id="c1", seed=1234), content=content)
    hero = _actor("hero", hp=20)
    hero.health.current = 5  # type: ignore[union-attr]
    engine.execute(CreateEntityCommand(entity=hero))

    check_events = engine.execute(
        RollCheckCommand(actor_id="hero", ability=Ability.STRENGTH, dc=10)
    )
    heal_events = engine.execute(
        ApplyEffectCommand(effect_id="lesser_heal", source_id="hero", target_id="hero")
    )

    assert check_events[0].type == "check_rolled"
    assert heal_events[0].type == "healing_applied"
    assert engine.world.entities["hero"].health is not None
    assert engine.world.entities["hero"].health.current > 5


def test_event_replay_restores_rng_counters_for_future_rolls() -> None:
    from rpg_engine.reducer import apply_event

    content = load_content_pack(Path("content/core"))
    original = SimulationEngine(WorldState(campaign_id="c1", seed=2026), content=content)
    original.execute(CreateEntityCommand(entity=_actor("hero", hp=50)))
    original.execute(CreateEntityCommand(entity=_actor("target", hp=50, armor_class=1)))

    snapshot = original.world.model_copy(deep=True)
    attack_events = original.execute(
        AttackTargetCommand(attacker_id="hero", target_id="target", weapon_id="longsword")
    )

    replayed_world = snapshot.model_copy(deep=True)
    for event in attack_events:
        apply_event(replayed_world, event)

    assert replayed_world.rng_counters == original.world.rng_counters
    assert replayed_world.entities["target"].health == original.world.entities["target"].health

    original_next = original.execute(
        AttackTargetCommand(attacker_id="hero", target_id="target", weapon_id="longsword")
    )
    replayed_next = SimulationEngine(replayed_world, content=content).execute(
        AttackTargetCommand(attacker_id="hero", target_id="target", weapon_id="longsword")
    )
    assert [event.model_dump(mode="json") for event in replayed_next] == [
        event.model_dump(mode="json") for event in original_next
    ]
