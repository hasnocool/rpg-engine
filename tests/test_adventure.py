"""v0.3 adventure engine behavior and replay tests."""

from pathlib import Path

import pytest

from rpg_engine.commands import (
    AdvanceQuestCommand,
    BuyItemCommand,
    ChooseDialogueOptionCommand,
    CreateEntityCommand,
    EquipItemCommand,
    ExploreLocationCommand,
    LootContainerCommand,
    SearchLocationCommand,
    SellItemCommand,
    SpawnNpcCommand,
    StartDialogueCommand,
    TravelCommand,
    UnequipItemCommand,
)
from rpg_engine.content.loader import load_content_pack, validate_content_registry
from rpg_engine.content.models import ContentRegistry, WorldConnectionSpec, WorldLocationSpec
from rpg_engine.engine import SimulationEngine, SimulationError
from rpg_engine.events import CheckRolledEvent, DiscoveryRevealedEvent, TransactionCompletedEvent
from rpg_engine.models import Entity, Health, Identity, Inventory, Position, Stats, WorldState
from rpg_engine.reducer import apply_event

CONTENT = Path("content/core")


def _hero(*, area: str = "village", gold: int = 40, items: list[str] | None = None) -> Entity:
    return Entity(
        id="hero",
        identity=Identity(name="Hero"),
        stats=Stats(strength=16, dexterity=14, wisdom=20, charisma=14),
        health=Health(current=24, maximum=24),
        position=Position(region="north_vale", area=area),
        inventory=Inventory(item_ids=list(items or []), currency={"gold": gold}),
    )


def _engine(
    *, seed: int = 1, area: str = "village", items: list[str] | None = None
) -> SimulationEngine:
    content = load_content_pack(CONTENT)
    engine = SimulationEngine(WorldState(campaign_id="adventure", seed=seed), content=content)
    engine.execute(CreateEntityCommand(entity=_hero(area=area, items=items)))
    return engine


def test_exploration_loot_and_equipment_are_authoritative() -> None:
    engine = _engine(items=["longsword"])

    explore_events = engine.execute(ExploreLocationCommand(actor_id="hero"))
    assert engine.world.knowledge["hero"].location_ids == {"village"}
    assert "supply_crate" in engine.world.knowledge["hero"].container_ids
    assert "supply_crate" in engine.world.containers
    assert any(event.type == "location_explored" for event in explore_events)

    engine.execute(LootContainerCommand(actor_id="hero", container_id="supply_crate"))
    hero = engine.world.entities["hero"]
    assert "healing_tonic" in hero.inventory.item_ids
    assert hero.inventory.currency["gold"] == 45
    assert engine.world.containers["supply_crate"].item_ids == []

    engine.execute(EquipItemCommand(actor_id="hero", item_id="longsword"))
    assert hero.inventory.equipment["hand"] == "longsword"
    assert "longsword" in hero.inventory.equipped_item_ids

    engine.execute(UnequipItemCommand(actor_id="hero", item_id="longsword"))
    assert hero.inventory.equipment == {}
    assert "longsword" not in hero.inventory.equipped_item_ids


def test_search_reveals_hidden_connection_and_travel_advances_time() -> None:
    engine = _engine(area="forest", seed=1)

    search_events = engine.execute(SearchLocationCommand(actor_id="hero"))
    assert any(isinstance(event, DiscoveryRevealedEvent) for event in search_events)
    knowledge = engine.world.knowledge["hero"]
    assert "old_road" in knowledge.discovery_ids
    assert "forest_ruins" in knowledge.connection_ids
    assert "ruins" in knowledge.location_ids
    assert "ruined_cache" in knowledge.container_ids

    before = engine.world.time_minutes
    travel_events = engine.execute(TravelCommand(actor_id="hero", destination_id="ruins"))
    assert travel_events[0].type == "travel_completed"
    assert engine.world.entities["hero"].position.area == "ruins"
    assert engine.world.time_minutes == before + 20


def test_hidden_connection_is_not_usable_before_discovery() -> None:
    engine = _engine(area="forest", seed=1)
    try:
        engine.execute(TravelCommand(actor_id="hero", destination_id="ruins"))
    except SimulationError as exc:
        assert "no known traversable connection" in str(exc)
    else:
        raise AssertionError("hidden connection should require discovery")


def test_npc_dialogue_quest_and_requirement_flow() -> None:
    engine = _engine(seed=2)
    engine.execute(
        SpawnNpcCommand(template_id="blacksmith", entity_id="torvald", location_id="village")
    )

    start = engine.execute(StartDialogueCommand(actor_id="hero", npc_id="torvald"))
    session_id = start[0].session.id  # type: ignore[attr-defined]

    check_events = engine.execute(
        ChooseDialogueOptionCommand(actor_id="hero", session_id=session_id, option_id="persuade")
    )
    assert any(isinstance(event, CheckRolledEvent) for event in check_events)

    node_id = engine.world.dialogue_sessions[session_id].node_id
    end_option = "leave" if node_id == "work" else "goodbye"
    engine.execute(
        ChooseDialogueOptionCommand(actor_id="hero", session_id=session_id, option_id=end_option)
    )
    start = engine.execute(StartDialogueCommand(actor_id="hero", npc_id="torvald"))
    session_id = start[0].session.id  # type: ignore[attr-defined]
    engine.execute(
        ChooseDialogueOptionCommand(actor_id="hero", session_id=session_id, option_id="ask_work")
    )
    assert engine.world.quest_progress["hero"]["northern_road"].state == "offered"

    engine.execute(
        ChooseDialogueOptionCommand(actor_id="hero", session_id=session_id, option_id="accept_work")
    )
    assert engine.world.quest_progress["hero"]["northern_road"].state == "investigating"

    engine.execute(TravelCommand(actor_id="hero", destination_id="forest"))
    engine.execute(SearchLocationCommand(actor_id="hero"))
    engine.execute(
        AdvanceQuestCommand(actor_id="hero", quest_id="northern_road", trigger="road_found")
    )
    assert engine.world.quest_progress["hero"]["northern_road"].state == "ready_to_report"

    engine.execute(TravelCommand(actor_id="hero", destination_id="village"))
    start = engine.execute(StartDialogueCommand(actor_id="hero", npc_id="torvald"))
    session_id = start[0].session.id  # type: ignore[attr-defined]
    engine.execute(
        ChooseDialogueOptionCommand(actor_id="hero", session_id=session_id, option_id="report_work")
    )
    engine.execute(
        ChooseDialogueOptionCommand(
            actor_id="hero", session_id=session_id, option_id="report_findings"
        )
    )
    progress = engine.world.quest_progress["hero"]["northern_road"]
    assert progress.state == "complete"
    assert progress.completed is True


def test_merchant_buy_and_sell_use_content_prices() -> None:
    engine = _engine(seed=3)
    engine.execute(
        SpawnNpcCommand(template_id="blacksmith", entity_id="torvald", location_id="village")
    )

    buy_events = engine.execute(
        BuyItemCommand(actor_id="hero", merchant_id="torvald", item_id="longsword")
    )
    transaction = next(
        event for event in buy_events if isinstance(event, TransactionCompletedEvent)
    )
    assert transaction.unit_price == 15
    assert transaction.total == 15
    assert engine.world.entities["hero"].inventory.currency["gold"] == 25
    assert "longsword" in engine.world.entities["hero"].inventory.item_ids

    sell_events = engine.execute(
        SellItemCommand(actor_id="hero", merchant_id="torvald", item_id="longsword")
    )
    transaction = next(
        event for event in sell_events if isinstance(event, TransactionCompletedEvent)
    )
    assert transaction.unit_price == 7
    assert engine.world.entities["hero"].inventory.currency["gold"] == 32


def test_adventure_events_replay_to_identical_world_state() -> None:
    engine = _engine(seed=1, items=["longsword"])
    snapshot = engine.world.model_copy(deep=True)
    emitted = []

    for command in (
        ExploreLocationCommand(actor_id="hero"),
        LootContainerCommand(actor_id="hero", container_id="supply_crate"),
        EquipItemCommand(actor_id="hero", item_id="longsword"),
        SpawnNpcCommand(template_id="blacksmith", entity_id="torvald", location_id="village"),
        BuyItemCommand(actor_id="hero", merchant_id="torvald", item_id="healing_tonic"),
        StartDialogueCommand(actor_id="hero", npc_id="torvald"),
    ):
        emitted.extend(engine.execute(command))

    replayed = snapshot.model_copy(deep=True)
    for event in emitted:
        apply_event(replayed, event)

    assert replayed == engine.world


def test_content_registry_rejects_broken_cross_file_references() -> None:
    registry = ContentRegistry.with_core_defaults()
    registry.locations["village"] = WorldLocationSpec(id="village", name="Village")
    registry.connections["broken"] = WorldConnectionSpec(
        id="broken",
        from_location_id="village",
        to_location_id="missing",
    )

    with pytest.raises(ValueError, match="unknown locations: missing"):
        validate_content_registry(registry)


def test_quest_commands_require_an_existing_actor() -> None:
    engine = _engine(seed=4)

    with pytest.raises(SimulationError, match="unknown entity: missing"):
        engine.execute(
            AdvanceQuestCommand(
                actor_id="missing",
                quest_id="northern_road",
                trigger="accept",
            )
        )
