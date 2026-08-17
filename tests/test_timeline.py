"""v0.2.1 first-class timeline behavior, integration, and replay tests."""

import pytest

from rpg_engine.commands import (
    AdvanceTimeCommand,
    AdvanceTimelineCommand,
    ConfigureTimelineCommand,
    CreateEntityCommand,
    EndTurnCommand,
    ScheduleTimelineItemCommand,
    SetTimelinePausedCommand,
    StartEncounterCommand,
    SyncTimelineCommand,
)
from rpg_engine.engine import SimulationError
from rpg_engine.events import TimelineAdvancedEvent, TimelineItemFiredEvent
from rpg_engine.models import Entity, Identity, WorldState
from rpg_engine.reducer import apply_event
from rpg_engine.temporal import TimelineSimulationEngine
from rpg_engine.timeline import (
    TimelineAdvanceSource,
    TimelineError,
    TimelineItemKind,
    TimelineScheduler,
    TimelineState,
    TimeMode,
)


def test_all_time_modes_have_explicit_advance_policies() -> None:
    manual_modes = {TimeMode.TURN_BASED, TimeMode.TIMED_TURN_BASED, TimeMode.HYBRID}
    wall_modes = {
        TimeMode.TIMED_TURN_BASED,
        TimeMode.REAL_TIME,
        TimeMode.REAL_TIME_WITH_PAUSE,
        TimeMode.HYBRID,
    }
    for mode in TimeMode:
        scheduler = TimelineScheduler(TimelineState(mode=mode))
        if mode in manual_modes:
            assert scheduler.advance(1).delta_ms == 1
        else:
            with pytest.raises(TimelineError, match="explicit advancement"):
                scheduler.advance(1)
        if mode in wall_modes:
            assert scheduler.sync_wall_clock(1_000).delta_ms == 0
        else:
            with pytest.raises(TimelineError, match="wall-clock sync"):
                scheduler.sync_wall_clock(1_000)


def test_same_queue_orders_every_requested_timeline_kind_deterministically() -> None:
    scheduler = TimelineScheduler(TimelineState())
    kinds = [
        TimelineItemKind.ACTOR_READY,
        TimelineItemKind.DELAYED_ACTION,
        TimelineItemKind.SPELL_COMPLETION,
        TimelineItemKind.CONDITION_TICK,
        TimelineItemKind.WORLD_EVENT,
        TimelineItemKind.NPC_SCHEDULE,
        TimelineItemKind.REACTION_WINDOW,
        TimelineItemKind.IDLE_PRESSURE,
    ]
    for index, kind in enumerate(kinds):
        scheduler.schedule(f"item-{index}", kind, delay_ms=250)

    result = scheduler.advance(250)
    assert [firing.item.kind for firing in result.fired] == kinds
    assert scheduler.state.queue == {}


def test_recurring_items_are_bounded_and_backlog_can_be_drained() -> None:
    scheduler = TimelineScheduler(TimelineState())
    scheduler.schedule(
        "heartbeat",
        TimelineItemKind.WORLD_EVENT,
        delay_ms=1,
        interval_ms=1,
        remaining_occurrences=10,
    )
    result = scheduler.advance(10, max_firings=3)
    assert len(result.fired) == 3
    assert result.backlog is True

    total = len(result.fired)
    while scheduler.state.queue:
        drained = scheduler.drain_due(max_firings=3)
        total += len(drained.fired)
        if not drained.backlog:
            break
    assert total == 10
    assert scheduler.state.queue == {}


def test_real_time_with_pause_discards_paused_elapsed_wall_time() -> None:
    engine = TimelineSimulationEngine(WorldState(campaign_id="clock", seed=1))
    engine.execute(ConfigureTimelineCommand(mode=TimeMode.REAL_TIME_WITH_PAUSE))
    engine.execute(SyncTimelineCommand(wall_time_ms=1_000))
    engine.execute(SyncTimelineCommand(wall_time_ms=1_250))
    engine.execute(SetTimelinePausedCommand(paused=True, wall_time_ms=1_250))
    engine.execute(SyncTimelineCommand(wall_time_ms=9_000))
    engine.execute(SetTimelinePausedCommand(paused=False, wall_time_ms=9_000))
    engine.execute(SyncTimelineCommand(wall_time_ms=9_100))
    assert engine.world.timeline.now_ms == 350


def test_timeline_events_replay_to_exact_world_state() -> None:
    engine = TimelineSimulationEngine(WorldState(campaign_id="replay-time", seed=2))
    events = []
    events += engine.execute(
        ConfigureTimelineCommand(
            mode=TimeMode.TIMED_TURN_BASED,
            turn_quantum_ms=5_000,
            turn_timeout_ms=20_000,
        )
    )
    events += engine.execute(
        ScheduleTimelineItemCommand(
            item_id="spell:1",
            kind=TimelineItemKind.SPELL_COMPLETION,
            delay_ms=5_000,
            actor_id="mage",
            payload={"spell_id": "example"},
        )
    )
    events += engine.execute(AdvanceTimelineCommand(delta_ms=5_000))

    replayed = WorldState(campaign_id="replay-time", seed=2)
    for event in events:
        apply_event(replayed, event)
    assert replayed == engine.world


def test_encounter_turns_emit_actor_readiness_and_idle_pressure_on_same_timeline() -> None:
    engine = TimelineSimulationEngine(WorldState(campaign_id="encounter-time", seed=3))
    engine.execute(CreateEntityCommand(entity=Entity(id="a", identity=Identity(name="A"))))
    engine.execute(CreateEntityCommand(entity=Entity(id="b", identity=Identity(name="B"))))
    events = engine.execute(
        StartEncounterCommand(encounter_id="fight", participant_ids=["a", "b"])
    )
    ready = [event for event in events if isinstance(event, TimelineItemFiredEvent)]
    assert len(ready) == 1
    assert ready[0].item.kind == TimelineItemKind.ACTOR_READY
    active = engine.world.encounters["fight"].active_actor_id
    assert active is not None
    idle_items = list(engine.world.timeline.queue.values())
    assert len(idle_items) == 1
    assert idle_items[0].kind == TimelineItemKind.IDLE_PRESSURE
    assert idle_items[0].actor_id == active

    events = engine.execute(EndTurnCommand(actor_id=active, encounter_id="fight"))
    advance = next(event for event in events if isinstance(event, TimelineAdvancedEvent))
    assert advance.source == TimelineAdvanceSource.TURN
    assert advance.delta_ms == engine.world.timeline.turn_quantum_ms
    ready = [
        event
        for event in events
        if isinstance(event, TimelineItemFiredEvent)
        and event.item.kind == TimelineItemKind.ACTOR_READY
    ]
    assert len(ready) == 1
    assert ready[0].item.actor_id == engine.world.encounters["fight"].active_actor_id
    assert len(engine.world.timeline.queue) == 1


def test_legacy_world_time_command_advances_the_first_class_timeline() -> None:
    engine = TimelineSimulationEngine(WorldState(campaign_id="legacy-time", seed=4))
    events = engine.execute(AdvanceTimeCommand(minutes=2))
    advance = next(event for event in events if isinstance(event, TimelineAdvancedEvent))
    assert advance.source == TimelineAdvanceSource.LEGACY_WORLD_TIME
    assert engine.world.timeline.now_ms == 120_000
    assert engine.world.time_minutes == 2


def test_real_time_mode_rejects_manual_timeline_advance() -> None:
    engine = TimelineSimulationEngine(WorldState(campaign_id="real-time", seed=5))
    engine.execute(ConfigureTimelineCommand(mode=TimeMode.REAL_TIME))
    with pytest.raises(SimulationError, match="explicit advancement"):
        engine.execute(AdvanceTimelineCommand(delta_ms=1))
