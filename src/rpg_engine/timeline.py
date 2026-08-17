"""Deterministic first-class timeline and scheduler primitives."""

from __future__ import annotations

import heapq
from enum import StrEnum
from typing import Protocol, TypedDict, Unpack

from pydantic import BaseModel, ConfigDict, Field, model_validator


type TimelinePayloadValue = str | int | float | bool | None
type TimelinePayload = dict[str, TimelinePayloadValue]


class TimelineError(ValueError):
    """Rejected timeline operation or invalid time-mode transition."""


class TimelineModel(BaseModel):
    """Strict base model for persisted timeline contracts."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class TimeMode(StrEnum):
    TURN_BASED = "turn_based"
    TIMED_TURN_BASED = "timed_turn_based"
    REAL_TIME = "real_time"
    REAL_TIME_WITH_PAUSE = "real_time_with_pause"
    HYBRID = "hybrid"


class TimelineItemKind(StrEnum):
    ACTOR_READY = "actor_ready"
    DELAYED_ACTION = "delayed_action"
    SPELL_COMPLETION = "spell_completion"
    CONDITION_TICK = "condition_tick"
    WORLD_EVENT = "world_event"
    NPC_SCHEDULE = "npc_schedule"
    REACTION_WINDOW = "reaction_window"
    IDLE_PRESSURE = "idle_pressure"
    CUSTOM = "custom"


class TimelineAdvanceSource(StrEnum):
    MANUAL = "manual"
    TURN = "turn"
    WALL_CLOCK = "wall_clock"
    LEGACY_WORLD_TIME = "legacy_world_time"
    DRAIN = "drain"


class TimelineItem(TimelineModel):
    id: str
    kind: TimelineItemKind
    due_ms: int = Field(ge=0)
    priority: int = 0
    order: int = Field(ge=0)
    actor_id: str | None = None
    payload: TimelinePayload = Field(default_factory=dict)
    interval_ms: int | None = Field(default=None, gt=0)
    remaining_occurrences: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_recurrence(self) -> TimelineItem:
        if self.interval_ms is None and self.remaining_occurrences not in (None, 1):
            raise ValueError("remaining_occurrences greater than one requires interval_ms")
        return self


class TimelineState(TimelineModel):
    mode: TimeMode = TimeMode.TURN_BASED
    now_ms: int = Field(default=0, ge=0)
    turn_quantum_ms: int = Field(default=6_000, gt=0)
    turn_timeout_ms: int = Field(default=30_000, gt=0)
    wall_clock_anchor_ms: int | None = Field(default=None, ge=0)
    paused: bool = False
    next_order: int = Field(default=0, ge=0)
    queue: dict[str, TimelineItem] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_pause_mode(self) -> TimelineState:
        if self.paused and self.mode not in {
            TimeMode.REAL_TIME_WITH_PAUSE,
            TimeMode.HYBRID,
        }:
            raise ValueError(f"timeline mode {self.mode.value!r} does not support pause")
        return self


class TimelineFiring(TimelineModel):
    item: TimelineItem
    rescheduled_item: TimelineItem | None = None


class TimelineAdvanceResult(TimelineModel):
    source: TimelineAdvanceSource
    previous_ms: int = Field(ge=0)
    now_ms: int = Field(ge=0)
    delta_ms: int = Field(ge=0)
    wall_clock_anchor_ms: int | None = Field(default=None, ge=0)
    fired: list[TimelineFiring] = Field(default_factory=list)
    backlog: bool = False


class ScheduleOptions(TypedDict, total=False):
    delay_ms: int
    due_ms: int
    priority: int
    payload: TimelinePayload
    interval_ms: int
    remaining_occurrences: int
    replace: bool


class TimelineOwner(Protocol):
    timeline: TimelineState
    time_minutes: int


_MANUAL_MODES = {
    TimeMode.TURN_BASED,
    TimeMode.TIMED_TURN_BASED,
    TimeMode.HYBRID,
}
_WALL_CLOCK_MODES = {
    TimeMode.TIMED_TURN_BASED,
    TimeMode.REAL_TIME,
    TimeMode.REAL_TIME_WITH_PAUSE,
    TimeMode.HYBRID,
}
_PAUSABLE_MODES = {TimeMode.REAL_TIME_WITH_PAUSE, TimeMode.HYBRID}


class TimelineScheduler:
    """Bounded, non-blocking deterministic scheduler over persisted timeline state.

    The scheduler never sleeps and never reads a clock itself. Real-time modes advance only from an
    explicit monotonic millisecond value supplied by the caller, so replay uses the same inputs and
    produces the same ordering.
    """

    def __init__(self, owner: TimelineOwner | TimelineState) -> None:
        if isinstance(owner, TimelineState):
            self._owner: TimelineOwner | None = None
            self.state = owner
        else:
            self._owner = owner
            self.state = owner.timeline
            if self.state.now_ms == 0 and owner.time_minutes > 0:
                self.state.now_ms = owner.time_minutes * 60_000
            self._sync_legacy_minutes()

    @property
    def supports_turn_advance(self) -> bool:
        return self.state.mode in _MANUAL_MODES

    @property
    def supports_wall_clock(self) -> bool:
        return self.state.mode in _WALL_CLOCK_MODES

    @property
    def supports_pause(self) -> bool:
        return self.state.mode in _PAUSABLE_MODES

    def _sync_legacy_minutes(self) -> None:
        if self._owner is not None:
            self._owner.time_minutes = self.state.now_ms // 60_000

    def configure(
        self,
        mode: TimeMode,
        *,
        turn_quantum_ms: int | None = None,
        turn_timeout_ms: int | None = None,
    ) -> TimelineState:
        if mode not in _PAUSABLE_MODES and self.state.paused:
            self.state.paused = False
        self.state.mode = mode
        if turn_quantum_ms is not None:
            if turn_quantum_ms <= 0:
                raise TimelineError("turn_quantum_ms must be positive")
            self.state.turn_quantum_ms = turn_quantum_ms
        if turn_timeout_ms is not None:
            if turn_timeout_ms <= 0:
                raise TimelineError("turn_timeout_ms must be positive")
            self.state.turn_timeout_ms = turn_timeout_ms
        self.state.wall_clock_anchor_ms = None
        return self.state.model_copy(deep=True)

    def set_paused(self, paused: bool) -> bool:
        if self.state.mode not in _PAUSABLE_MODES:
            raise TimelineError(f"timeline mode {self.state.mode.value!r} does not support pause")
        self.state.paused = paused
        return self.state.paused

    def schedule(
        self,
        item_id: str,
        kind: TimelineItemKind,
        *,
        delay_ms: int | None = None,
        due_ms: int | None = None,
        priority: int = 0,
        actor_id: str | None = None,
        payload: TimelinePayload | None = None,
        interval_ms: int | None = None,
        remaining_occurrences: int | None = None,
        replace: bool = False,
    ) -> TimelineItem:
        if delay_ms is not None and due_ms is not None:
            raise TimelineError("provide delay_ms or due_ms, not both")
        if delay_ms is not None and delay_ms < 0:
            raise TimelineError("delay_ms cannot be negative")
        if due_ms is not None and due_ms < 0:
            raise TimelineError("due_ms cannot be negative")
        if item_id in self.state.queue and not replace:
            raise TimelineError(f"timeline item already exists: {item_id}")

        resolved_due_ms = (
            due_ms
            if due_ms is not None
            else self.state.now_ms + (delay_ms if delay_ms is not None else 0)
        )
        item = TimelineItem(
            id=item_id,
            kind=kind,
            due_ms=resolved_due_ms,
            priority=priority,
            order=self.state.next_order,
            actor_id=actor_id,
            payload=dict(payload or {}),
            interval_ms=interval_ms,
            remaining_occurrences=remaining_occurrences,
        )
        self.state.next_order += 1
        self.state.queue[item.id] = item
        return item.model_copy(deep=True)

    def cancel(self, item_id: str) -> TimelineItem | None:
        item = self.state.queue.pop(item_id, None)
        return item.model_copy(deep=True) if item is not None else None

    def schedule_actor_ready(
        self, item_id: str, actor_id: str, **kwargs: Unpack[ScheduleOptions]
    ) -> TimelineItem:
        return self._schedule_typed(item_id, TimelineItemKind.ACTOR_READY, actor_id, kwargs)

    def schedule_delayed_action(
        self, item_id: str, actor_id: str | None = None, **kwargs: Unpack[ScheduleOptions]
    ) -> TimelineItem:
        return self._schedule_typed(item_id, TimelineItemKind.DELAYED_ACTION, actor_id, kwargs)

    def schedule_spell_completion(
        self, item_id: str, actor_id: str | None = None, **kwargs: Unpack[ScheduleOptions]
    ) -> TimelineItem:
        return self._schedule_typed(item_id, TimelineItemKind.SPELL_COMPLETION, actor_id, kwargs)

    def schedule_condition_tick(
        self, item_id: str, actor_id: str | None = None, **kwargs: Unpack[ScheduleOptions]
    ) -> TimelineItem:
        return self._schedule_typed(item_id, TimelineItemKind.CONDITION_TICK, actor_id, kwargs)

    def schedule_world_event(
        self, item_id: str, **kwargs: Unpack[ScheduleOptions]
    ) -> TimelineItem:
        return self._schedule_typed(item_id, TimelineItemKind.WORLD_EVENT, None, kwargs)

    def schedule_npc_schedule(
        self, item_id: str, actor_id: str | None = None, **kwargs: Unpack[ScheduleOptions]
    ) -> TimelineItem:
        return self._schedule_typed(item_id, TimelineItemKind.NPC_SCHEDULE, actor_id, kwargs)

    def schedule_reaction_window(
        self, item_id: str, actor_id: str | None = None, **kwargs: Unpack[ScheduleOptions]
    ) -> TimelineItem:
        return self._schedule_typed(item_id, TimelineItemKind.REACTION_WINDOW, actor_id, kwargs)

    def schedule_idle_pressure(
        self, item_id: str, actor_id: str | None = None, **kwargs: Unpack[ScheduleOptions]
    ) -> TimelineItem:
        return self._schedule_typed(item_id, TimelineItemKind.IDLE_PRESSURE, actor_id, kwargs)

    def _schedule_typed(
        self,
        item_id: str,
        kind: TimelineItemKind,
        actor_id: str | None,
        kwargs: ScheduleOptions,
    ) -> TimelineItem:
        return self.schedule(item_id, kind, actor_id=actor_id, **kwargs)

    @staticmethod
    def _heap_key(item: TimelineItem) -> tuple[int, int, int, str]:
        return (item.due_ms, item.priority, item.order, item.id)

    def _drain_due(
        self,
        *,
        source: TimelineAdvanceSource,
        previous_ms: int,
        delta_ms: int,
        max_firings: int,
    ) -> TimelineAdvanceResult:
        if max_firings <= 0:
            raise TimelineError("max_firings must be positive")
        heap = [
            self._heap_key(item)
            for item in self.state.queue.values()
            if item.due_ms <= self.state.now_ms
        ]
        heapq.heapify(heap)
        fired: list[TimelineFiring] = []

        while heap and len(fired) < max_firings:
            due_ms, priority, order, item_id = heapq.heappop(heap)
            current = self.state.queue.get(item_id)
            if current is None or self._heap_key(current) != (due_ms, priority, order, item_id):
                continue
            self.state.queue.pop(item_id)
            fired_item = current.model_copy(deep=True)
            rescheduled: TimelineItem | None = None
            should_repeat = current.interval_ms is not None and (
                current.remaining_occurrences is None or current.remaining_occurrences > 1
            )
            if should_repeat:
                remaining = (
                    None
                    if current.remaining_occurrences is None
                    else current.remaining_occurrences - 1
                )
                rescheduled = current.model_copy(
                    update={
                        "due_ms": current.due_ms + current.interval_ms,
                        "remaining_occurrences": remaining,
                    },
                    deep=True,
                )
                self.state.queue[item_id] = rescheduled
                if rescheduled.due_ms <= self.state.now_ms:
                    heapq.heappush(heap, self._heap_key(rescheduled))
            fired.append(
                TimelineFiring(
                    item=fired_item,
                    rescheduled_item=(
                        rescheduled.model_copy(deep=True) if rescheduled is not None else None
                    ),
                )
            )

        backlog = any(item.due_ms <= self.state.now_ms for item in self.state.queue.values())
        return TimelineAdvanceResult(
            source=source,
            previous_ms=previous_ms,
            now_ms=self.state.now_ms,
            delta_ms=delta_ms,
            wall_clock_anchor_ms=self.state.wall_clock_anchor_ms,
            fired=fired,
            backlog=backlog,
        )

    def drain_due(self, *, max_firings: int = 10_000) -> TimelineAdvanceResult:
        return self._drain_due(
            source=TimelineAdvanceSource.DRAIN,
            previous_ms=self.state.now_ms,
            delta_ms=0,
            max_firings=max_firings,
        )

    def advance(
        self,
        delta_ms: int,
        *,
        source: TimelineAdvanceSource = TimelineAdvanceSource.MANUAL,
        max_firings: int = 10_000,
    ) -> TimelineAdvanceResult:
        if delta_ms <= 0:
            raise TimelineError("delta_ms must be positive")
        if source not in {TimelineAdvanceSource.MANUAL, TimelineAdvanceSource.TURN}:
            raise TimelineError("advance() only accepts manual or turn sources")
        if self.state.mode not in _MANUAL_MODES:
            raise TimelineError(
                f"timeline mode {self.state.mode.value!r} does not support explicit advancement"
            )
        previous_ms = self.state.now_ms
        self.state.now_ms += delta_ms
        self._sync_legacy_minutes()
        return self._drain_due(
            source=source,
            previous_ms=previous_ms,
            delta_ms=delta_ms,
            max_firings=max_firings,
        )

    def advance_turn(
        self, *, turns: int = 1, max_firings: int = 10_000
    ) -> TimelineAdvanceResult:
        if turns <= 0:
            raise TimelineError("turns must be positive")
        return self.advance(
            self.state.turn_quantum_ms * turns,
            source=TimelineAdvanceSource.TURN,
            max_firings=max_firings,
        )

    def advance_legacy_world_time(
        self, minutes: int, *, max_firings: int = 10_000
    ) -> TimelineAdvanceResult:
        if minutes <= 0:
            raise TimelineError("minutes must be positive")
        previous_ms = self.state.now_ms
        delta_ms = minutes * 60_000
        self.state.now_ms += delta_ms
        self._sync_legacy_minutes()
        return self._drain_due(
            source=TimelineAdvanceSource.LEGACY_WORLD_TIME,
            previous_ms=previous_ms,
            delta_ms=delta_ms,
            max_firings=max_firings,
        )

    def sync_wall_clock(
        self, wall_time_ms: int, *, max_firings: int = 10_000
    ) -> TimelineAdvanceResult:
        if wall_time_ms < 0:
            raise TimelineError("wall_time_ms cannot be negative")
        if self.state.mode not in _WALL_CLOCK_MODES:
            raise TimelineError(
                f"timeline mode {self.state.mode.value!r} does not support wall-clock sync"
            )
        previous_ms = self.state.now_ms
        anchor = self.state.wall_clock_anchor_ms
        if anchor is None:
            delta_ms = 0
        else:
            if wall_time_ms < anchor:
                raise TimelineError("wall_time_ms must be monotonic")
            delta_ms = 0 if self.state.paused else wall_time_ms - anchor
            self.state.now_ms += delta_ms
        self.state.wall_clock_anchor_ms = wall_time_ms
        self._sync_legacy_minutes()
        return self._drain_due(
            source=TimelineAdvanceSource.WALL_CLOCK,
            previous_ms=previous_ms,
            delta_ms=delta_ms,
            max_firings=max_firings,
        )