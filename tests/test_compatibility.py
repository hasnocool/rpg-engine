"""Compatibility checks for v0.1 command behavior outside encounters."""

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


def test_v01_commands_remain_valid_outside_encounters() -> None:
    content = load_content_pack(Path("content/core"))
    engine = SimulationEngine(WorldState(campaign_id="c1", seed=5), content=content)
    engine.execute(CreateEntityCommand(entity=_actor("hero")))
    engine.execute(CreateEntityCommand(entity=_actor("target", armor_class=1)))
    events = engine.execute(
        AttackTargetCommand(
            attacker_id="hero", target_id="target", weapon_id="longsword"
        )
    )
    assert isinstance(events[0], AttackRolledEvent)
    assert any(isinstance(event, DamageAppliedEvent) for event in events)
    check = engine.execute(RollCheckCommand(actor_id="hero", ability=Ability.STRENGTH, dc=10))[0]
    assert check.type == "check_rolled"
    engine.world.entities["hero"].health.current = 5  # type: ignore[union-attr]
    heal = engine.execute(
        ApplyEffectCommand(
            effect_id="lesser_heal", source_id="hero", target_id="hero"
        )
    )[0]
    assert heal.type == "healing_applied"
