"""v0.4 living-world behavior, scheduling, determinism, and replay tests."""

from pathlib import Path

from rpg_engine.commands import (
    AdjustFactionRelationCommand,
    AdjustReputationCommand,
    CompleteDynamicQuestCommand,
    GenerateRumorCommand,
    HarvestResourceCommand,
    InitializeLivingWorldCommand,
    ResolveOffscreenEncounterCommand,
)
from rpg_engine.content.loader import load_content_pack
from rpg_engine.dice import DeterministicRNG
from rpg_engine.events import Event, EventBase, TimelineAdvancedEvent, TimelineItemFiredEvent
from rpg_engine.living import LivingWorldRuntime
from rpg_engine.models import Entity, Health, Identity, Position, Stats, WorldState
from rpg_engine.reducer import apply_event
from rpg_engine.timeline import TimelineAdvanceSource, TimelineScheduler

CONTENT = load_content_pack(Path("content/core"))


def actor(entity_id: str, *, area: str = "village", strength: int = 12) -> Entity:
    return Entity(
        id=entity_id,
        identity=Identity(name=entity_id),
        stats=Stats(strength=strength, dexterity=12, armor_class=12),
        health=Health(current=30, maximum=30),
        position=Position(region="north_vale", area=area),
    )


def runtime(world: WorldState) -> LivingWorldRuntime:
    timeline = TimelineScheduler(world)
    return LivingWorldRuntime(
        world,
        content=CONTENT,
        rng=DeterministicRNG(world.seed, world.rng_counters),
        timeline=timeline,
    )


def stamp(world: WorldState, raw_events: list[EventBase]) -> list[Event]:
    stamped: list[Event] = []
    for event in raw_events:
        world.sequence += 1
        world.event_count += 1
        stamped.append(
            event.model_copy(
                update={
                    "sequence": world.sequence,
                    "campaign_id": world.campaign_id,
                    "rng_counters_after": dict(world.rng_counters),
                }
            )
        )
    return stamped  # type: ignore[return-value]


def advance_jobs(
    world: WorldState,
    living: LivingWorldRuntime,
    minutes: int,
) -> list[Event]:
    result = living.timeline.advance_legacy_world_time(minutes)
    raw: list[EventBase] = [
        TimelineAdvancedEvent(
            source=TimelineAdvanceSource.LEGACY_WORLD_TIME,
            delta_ms=result.delta_ms,
            time_ms=result.now_ms,
            wall_clock_anchor_ms=result.wall_clock_anchor_ms,
            backlog=result.backlog,
        )
    ]
    for firing in result.fired:
        raw.extend(living.calendar_events(firing.item.due_ms))
        raw.extend(living.expire_dynamic_quests(firing.item.due_ms // 60_000))
        raw.append(
            TimelineItemFiredEvent(
                item=firing.item,
                fired_at_ms=firing.item.due_ms,
                rescheduled_item=firing.rescheduled_item,
            )
        )
        raw.extend(living.on_timeline_item(firing.item))
    raw.extend(living.calendar_events(result.now_ms))
    raw.extend(living.expire_dynamic_quests(result.now_ms // 60_000))
    return stamp(world, raw)


def test_initialization_creates_persisted_living_world_and_recurring_jobs() -> None:
    world = WorldState(campaign_id="living", seed=44)
    living = runtime(world)
    events = stamp(world, living.execute(InitializeLivingWorldCommand()))

    assert world.living_world_initialized
    assert world.calendar.calendar_id == "common"
    assert "north_vale" in world.weather
    assert world.faction_relations["riverdale"]["road_raiders"] == -35
    assert "riverdale" in world.settlements
    assert world.resource_nodes["moonleaf_patch"].amount == 8
    assert any(event.type == "timeline_item_scheduled" for event in events)
    assert {
        "living:weather:north_vale",
        "living:economy:riverdale",
        "living:npc-schedule:blacksmith_daily",
        "living:ecology:moonleaf_patch",
        "living:rumor:road_raiders",
    } <= set(world.timeline.queue)


def test_recurring_jobs_advance_calendar_economy_weather_and_ecology() -> None:
    world = WorldState(campaign_id="jobs", seed=45)
    living = runtime(world)
    stamp(world, living.execute(InitializeLivingWorldCommand()))
    world.resource_nodes["moonleaf_patch"].amount = 1
    treasury_before = world.settlements["riverdale"].treasury
    weather_before = world.weather["north_vale"].updated_at_minute

    events = advance_jobs(world, living, 360)

    assert world.calendar.absolute_minute == 360
    assert world.settlements["riverdale"].treasury > treasury_before
    assert world.weather["north_vale"].updated_at_minute == 360
    assert world.weather["north_vale"].updated_at_minute > weather_before
    assert world.resource_nodes["moonleaf_patch"].amount > 1
    assert any(event.type == "settlement_economy_ticked" for event in events)
    assert any(event.type == "resource_regenerated" for event in events)


def test_npc_schedule_catches_up_at_each_due_time() -> None:
    world = WorldState(campaign_id="npc-schedule", seed=46)
    npc = actor("torvald")
    world.entities[npc.id] = npc
    world.entity_templates[npc.id] = "blacksmith"
    living = runtime(world)
    stamp(world, living.execute(InitializeLivingWorldCommand()))

    events = advance_jobs(world, living, 1080)

    assert world.entities["torvald"].position.area == "forest"
    assert world.npc_schedules["torvald"].activity == "gathering_charcoal"
    schedule_events = [event for event in events if event.type == "npc_schedule_applied"]
    assert [event.schedule.activity for event in schedule_events] == [
        "sleeping",
        "working",
        "gathering_charcoal",
    ]


def test_faction_reputation_and_offscreen_resolution_are_authoritative() -> None:
    first = WorldState(campaign_id="one", seed=2026)
    second = WorldState(campaign_id="two", seed=2026)
    for world in (first, second):
        world.entities["guard"] = actor("guard", area="forest", strength=16)
        world.entities["raider"] = actor("raider", area="forest", strength=13)
        living = runtime(world)
        stamp(world, living.execute(InitializeLivingWorldCommand()))
        stamp(
            world,
            living.execute(
                AdjustFactionRelationCommand(
                    faction_a_id="riverdale",
                    faction_b_id="road_raiders",
                    delta=10,
                    reason="truce",
                )
            ),
        )
        stamp(
            world,
            living.execute(
                AdjustReputationCommand(
                    actor_id="guard", faction_id="riverdale", delta=25
                )
            ),
        )
        stamp(
            world,
            living.execute(
                ResolveOffscreenEncounterCommand(
                    encounter_id="road-skirmish",
                    attacker_ids=["guard"],
                    defender_ids=["raider"],
                    location_id="forest",
                )
            ),
        )

    assert first.faction_relations["riverdale"]["road_raiders"] == -25
    assert first.reputation["guard"]["riverdale"] == 25
    a = first.offscreen_encounters["road-skirmish"]
    b = second.offscreen_encounters["road-skirmish"]
    assert (a.attacker_score, a.defender_score, a.winner) == (
        b.attacker_score,
        b.defender_score,
        b.winner,
    )


def test_rumor_dynamic_quest_completion_and_resource_regeneration() -> None:
    world = WorldState(campaign_id="rumor", seed=77)
    world.entities["hero"] = actor("hero", area="forest")
    living = runtime(world)
    stamp(world, living.execute(InitializeLivingWorldCommand()))

    stamp(
        world,
        living.execute(HarvestResourceCommand(actor_id="hero", node_id="moonleaf_patch", amount=3)),
    )
    assert world.resource_nodes["moonleaf_patch"].amount == 5
    assert world.entities["hero"].inventory.item_ids.count("moonleaf") == 3
    advance_jobs(world, living, 360)
    assert world.resource_nodes["moonleaf_patch"].amount >= 7

    stamp(
        world,
        living.execute(GenerateRumorCommand(location_id="village", template_id="road_raiders")),
    )
    rumor = next(iter(world.rumors.values()))
    assert rumor.dynamic_quest_id is not None
    quest = world.dynamic_quests[rumor.dynamic_quest_id]
    world.entities["hero"].position = Position(region="north_vale", area=quest.target_location_id)
    stamp(
        world,
        living.execute(
            CompleteDynamicQuestCommand(actor_id="hero", quest_id=quest.id)
        ),
    )
    assert world.dynamic_quests[quest.id].status == "completed"
    assert world.entities["hero"].inventory.currency["gold"] == 18


def test_living_world_events_replay_to_identical_state() -> None:
    original = WorldState(campaign_id="replay", seed=99)
    original.entities["hero"] = actor("hero", area="forest")
    living = runtime(original)
    all_events: list[Event] = []
    all_events += stamp(original, living.execute(InitializeLivingWorldCommand()))
    all_events += stamp(
        original,
        living.execute(HarvestResourceCommand(actor_id="hero", node_id="moonleaf_patch", amount=2)),
    )
    all_events += advance_jobs(original, living, 360)
    all_events += stamp(
        original,
        living.execute(
            GenerateRumorCommand(location_id="village", template_id="road_raiders")
        ),
    )

    replayed = WorldState(campaign_id="replay", seed=99)
    replayed.entities["hero"] = actor("hero", area="forest")
    for event in all_events:
        apply_event(replayed, event)

    assert replayed == original