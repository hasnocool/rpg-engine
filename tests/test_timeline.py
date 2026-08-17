"""First-class scheduler regressions carried into v0.4."""

import pytest

from rpg_engine.timeline import (
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


def test_every_scheduler_kind_uses_one_deterministic_queue() -> None:
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


def test_recurring_jobs_are_bounded_and_backlog_can_be_drained() -> None:
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
    assert result.backlog

    total = len(result.fired)
    while scheduler.state.queue:
        drained = scheduler.drain_due(max_firings=3)
        total += len(drained.fired)
        if not drained.backlog:
            break
    assert total == 10
    assert scheduler.state.queue == {}


def test_real_time_pause_discards_paused_wall_clock_duration() -> None:
    scheduler = TimelineScheduler(TimelineState(mode=TimeMode.REAL_TIME_WITH_PAUSE))
    scheduler.sync_wall_clock(1_000)
    assert scheduler.sync_wall_clock(1_250).delta_ms == 250
    scheduler.set_paused(True)
    assert scheduler.sync_wall_clock(9_000).delta_ms == 0
    scheduler.set_paused(False)
    assert scheduler.sync_wall_clock(9_100).delta_ms == 100
    assert scheduler.state.now_ms == 350