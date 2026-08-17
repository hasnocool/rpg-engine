"""Timeline-aware authoritative engine used by v0.2.1 campaign services."""

from __future__ import annotations

from rpg_engine.commands import (
    AdvanceTimeCommand,
    AdvanceTimelineCommand,
    AdvanceTimelineTurnCommand,
    CancelTimelineItemCommand,
    Command,
    ConfigureTimelineCommand,
    DrainTimelineCommand,
    EndTurnCommand,
    ScheduleTimelineItemCommand,
    SetTimelinePausedCommand,
    StartEncounterCommand,
    SyncTimelineCommand,
)
from rpg_engine.content.models import ContentRegistry
from rpg_engine.engine import SimulationEngine, SimulationError
from rpg_engine.events import (
    Event,
    EventBase,
    TimelineAdvancedEvent,
    TimelineConfiguredEvent,
    TimelineItemCancelledEvent,
    TimelineItemFiredEvent,
    TimelineItemScheduledEvent,
    TimelinePauseChangedEvent,
)
from rpg_engine.hooks import HookRegistry
from rpg_engine.models import WorldState
from rpg_engine.rules.base import RulesRuntime
from rpg_engine.spatial import SpatialAdapter
from rpg_engine.timeline import (
    TimelineAdvanceResult,
    TimelineAdvanceSource,
    TimelineError,
    TimelineItem,
    TimelineItemKind,
    TimelineScheduler,
)


class TimelineSimulationEngine(SimulationEngine):
    """Simulation engine with one persisted scheduler for tactical and world time."""

    def __init__(
        self,
        world: WorldState,
        *,
        rules: RulesRuntime | None = None,
        content: ContentRegistry | None = None,
        spatial: SpatialAdapter | None = None,
        hooks: HookRegistry | None = None,
    ) -> None:
        super().__init__(world, rules=rules, content=content, spatial=spatial, hooks=hooks)
        self.timeline = TimelineScheduler(self.world)

    def _stamp_timeline(self, raw_events: list[EventBase]) -> list[Event]:
        return self._stamp(self._expand_hooks(raw_events))

    @staticmethod
    def _advance_events(result: TimelineAdvanceResult) -> list[EventBase]:
        events: list[EventBase] = [
            TimelineAdvancedEvent(
                source=result.source,
                previous_ms=result.previous_ms,
                now_ms=result.now_ms,
                delta_ms=result.delta_ms,
                firings=len(result.fired),
                backlog=result.backlog,
                wall_clock_anchor_ms=result.wall_clock_anchor_ms,
            )
        ]
        events.extend(
            TimelineItemFiredEvent(
                item=firing.item,
                fired_at_ms=result.now_ms,
                rescheduled_item=firing.rescheduled_item,
            )
            for firing in result.fired
        )
        return events

    def _schedule_turn_signals(
        self, encounter_id: str, *, advance_turn: bool
    ) -> list[EventBase]:
        encounter = self.world.encounters[encounter_id]
        actor_id = encounter.active_actor_id
        if actor_id is None:
            return []
        suffix = f"{encounter.id}:{encounter.round}:{encounter.turn_index}:{actor_id}"
        readiness_delay = (
            self.timeline.state.turn_quantum_ms
            if advance_turn and self.timeline.supports_turn_advance
            else 0
        )
        ready = self.timeline.schedule_actor_ready(
            f"actor-ready:{suffix}",
            actor_id,
            delay_ms=readiness_delay,
            payload={
                "encounter_id": encounter.id,
                "round": encounter.round,
                "turn_index": encounter.turn_index,
            },
        )
        events: list[EventBase] = [TimelineItemScheduledEvent(item=ready)]
        if advance_turn and self.timeline.supports_turn_advance:
            result = self.timeline.advance_turn()
        else:
            result = self.timeline.drain_due()
        events.extend(self._advance_events(result))

        idle = self.timeline.schedule_idle_pressure(
            f"idle-pressure:{suffix}",
            actor_id,
            delay_ms=self.timeline.state.turn_timeout_ms,
            priority=100,
            payload={
                "encounter_id": encounter.id,
                "round": encounter.round,
                "turn_index": encounter.turn_index,
            },
        )
        events.append(TimelineItemScheduledEvent(item=idle))
        return events

    def _cancel_actor_idle_pressure(self, actor_id: str) -> list[EventBase]:
        item_ids = sorted(
            item.id
            for item in self.timeline.state.queue.values()
            if item.kind == TimelineItemKind.IDLE_PRESSURE and item.actor_id == actor_id
        )
        events: list[EventBase] = []
        for item_id in item_ids:
            if self.timeline.cancel(item_id) is not None:
                events.append(TimelineItemCancelledEvent(item_id=item_id))
        return events

    def _execute_timeline_command(self, command: Command) -> list[Event] | None:
        try:
            if isinstance(command, ConfigureTimelineCommand):
                state = self.timeline.configure(
                    command.mode,
                    turn_quantum_ms=command.turn_quantum_ms,
                    turn_timeout_ms=command.turn_timeout_ms,
                )
                return self._stamp_timeline(
                    [
                        TimelineConfiguredEvent(
                            mode=state.mode,
                            turn_quantum_ms=state.turn_quantum_ms,
                            turn_timeout_ms=state.turn_timeout_ms,
                            paused=state.paused,
                            wall_clock_anchor_ms=state.wall_clock_anchor_ms,
                        )
                    ]
                )

            if isinstance(command, ScheduleTimelineItemCommand):
                item = self.timeline.schedule(
                    command.item_id,
                    command.kind,
                    delay_ms=command.delay_ms,
                    due_ms=command.due_ms,
                    priority=command.priority,
                    actor_id=command.actor_id,
                    payload=command.payload,
                    interval_ms=command.interval_ms,
                    remaining_occurrences=command.remaining_occurrences,
                    replace=command.replace,
                )
                return self._stamp_timeline([TimelineItemScheduledEvent(item=item)])

            if isinstance(command, CancelTimelineItemCommand):
                cancelled_item: TimelineItem | None = self.timeline.cancel(command.item_id)
                if cancelled_item is None:
                    raise TimelineError(f"unknown timeline item: {command.item_id}")
                return self._stamp_timeline(
                    [TimelineItemCancelledEvent(item_id=command.item_id)]
                )

            if isinstance(command, AdvanceTimelineCommand):
                result = self.timeline.advance(
                    command.delta_ms,
                    source=TimelineAdvanceSource.MANUAL,
                    max_firings=command.max_firings if command.max_firings is not None else 10_000,
                )
                return self._stamp_timeline(self._advance_events(result))

            if isinstance(command, AdvanceTimelineTurnCommand):
                result = self.timeline.advance_turn(
                    turns=command.turns,
                    max_firings=command.max_firings if command.max_firings is not None else 10_000,
                )
                return self._stamp_timeline(self._advance_events(result))

            if isinstance(command, SyncTimelineCommand):
                result = self.timeline.sync_wall_clock(
                    command.wall_time_ms,
                    max_firings=command.max_firings if command.max_firings is not None else 10_000,
                )
                return self._stamp_timeline(self._advance_events(result))

            if isinstance(command, SetTimelinePausedCommand):
                raw_events: list[EventBase] = []
                if (
                    command.wall_time_ms is None
                    and self.timeline.state.wall_clock_anchor_ms is not None
                ):
                    raise TimelineError(
                        "wall_time_ms is required when changing pause after wall-clock sync"
                    )
                if command.wall_time_ms is not None:
                    result = self.timeline.sync_wall_clock(
                        command.wall_time_ms,
                        max_firings=10_000,
                    )
                    raw_events.extend(self._advance_events(result))
                paused = self.timeline.set_paused(command.paused)
                raw_events.append(TimelinePauseChangedEvent(paused=paused))
                return self._stamp_timeline(raw_events)

            if isinstance(command, DrainTimelineCommand):
                max_firings = command.max_firings if command.max_firings is not None else 10_000
                result = self.timeline.drain_due(max_firings=max_firings)
                return self._stamp_timeline(self._advance_events(result))
        except TimelineError as exc:
            raise SimulationError(str(exc)) from exc
        return None

    def execute(self, command: Command) -> list[Event]:
        timeline_events = self._execute_timeline_command(command)
        if timeline_events is not None:
            return timeline_events

        base_events = super().execute(command)
        raw_events: list[EventBase] = []
        try:
            if isinstance(command, AdvanceTimeCommand):
                raw_events.extend(
                    self._advance_events(
                        self.timeline.advance_legacy_world_time(command.minutes)
                    )
                )
            elif isinstance(command, StartEncounterCommand):
                raw_events.extend(
                    self._schedule_turn_signals(command.encounter_id, advance_turn=False)
                )
            elif isinstance(command, EndTurnCommand):
                raw_events.extend(self._cancel_actor_idle_pressure(command.actor_id))
                encounter = self._active_encounter_for_actor(command.actor_id)
                if encounter is not None:
                    raw_events.extend(
                        self._schedule_turn_signals(encounter.id, advance_turn=True)
                    )
        except TimelineError as exc:
            raise SimulationError(str(exc)) from exc

        if not raw_events:
            return base_events
        return [*base_events, *self._stamp_timeline(raw_events)]
