# First-class time and scheduling

v0.2.1 makes time an authoritative simulation primitive rather than a collection of unrelated
turn counters and world-clock increments.

`WorldState.timeline` is persisted with snapshots. Timeline commands emit immutable events, and the
reducer reconstructs the queue, clock, recurrence state, pause state, and wall-clock anchor exactly.
The campaign service uses `TimelineSimulationEngine`, so REST and WebSocket clients use the same
scheduler as local authoritative execution.

## Modes

The scheduler supports five policies over the same integer-millisecond logical clock:

| Mode | Turn/manual advance | Wall-clock sync | Pause |
| --- | --- | --- | --- |
| `turn_based` | yes | no | no |
| `timed_turn_based` | yes | yes | no |
| `real_time` | no | yes | no |
| `real_time_with_pause` | no | yes | yes |
| `hybrid` | yes | yes | yes |

Wall-clock modes never call `sleep()` and never read a system clock themselves. Clients supply a
monotonic millisecond value through `sync_timeline`. The resulting delta is recorded in immutable
events, so replay is deterministic even though the original session used real elapsed time.

`timed_turn_based` is useful for turn authority plus real deadlines. `hybrid` intentionally allows
both explicit turn advancement and elapsed-time advancement for games where tactical turns coexist
with background clocks.

## One queue for game time

Every scheduled item has an absolute `due_ms`, priority, stable insertion order, optional actor,
small typed payload, and optional recurrence. The same queue supports:

- `actor_ready`
- `delayed_action`
- `spell_completion`
- `condition_tick`
- `world_event`
- `npc_schedule`
- `reaction_window`
- `idle_pressure`
- `custom`

Consumers react to `timeline_item_fired` just like any other immutable engine event. Ruleset hooks
can therefore translate a firing into domain-specific commands without adding a second scheduler.

## Deterministic ordering

Items fire by:

1. earliest `due_ms`;
2. lowest numeric priority;
3. insertion order;
4. item ID as a final stable tie-breaker.

Recurring items keep their original insertion order. A large time jump can make many recurrences
due at once, so every advance has a bounded `max_firings`. If the bound is reached,
`timeline_advanced.backlog` is true and a client can issue `drain_timeline` again. This prevents an
accidental long-running catch-up loop from blocking the campaign authority.

## Tactical bridge

The timeline-aware engine keeps v0.2 encounter behavior compatible while adding temporal signals:

- encounter start emits an immediate `actor_ready` firing;
- ending a turn advances the timeline by `turn_quantum_ms` in turn-capable modes;
- the next actor becomes ready through the same queue;
- each active actor gets an `idle_pressure` deadline at `turn_timeout_ms`;
- ending the actor's turn cancels its outstanding idle-pressure item;
- legacy `advance_time` advances the first-class timeline and keeps `time_minutes` as a compatibility
  view.

In pure real-time modes, turn changes do not manufacture elapsed time. Actor readiness is immediate,
and elapsed time advances only when the caller supplies a wall-clock sync.

## Command examples

Configure a hybrid campaign:

```json
{
  "type": "configure_timeline",
  "mode": "hybrid",
  "turn_quantum_ms": 6000,
  "turn_timeout_ms": 30000
}
```

Schedule a delayed spell completion:

```json
{
  "type": "schedule_timeline_item",
  "item_id": "spell:mage-1:meteor-7",
  "kind": "spell_completion",
  "delay_ms": 12000,
  "actor_id": "mage-1",
  "payload": {"spell_id": "meteor-7"}
}
```

Advance turn-based logical time:

```json
{
  "type": "advance_timeline_turn",
  "turns": 1
}
```

Synchronize a real-time clock. The value must be monotonic for that campaign session:

```json
{
  "type": "sync_timeline",
  "wall_time_ms": 91234567
}
```

Pause safely after a wall-clock anchor exists by supplying the current monotonic value:

```json
{
  "type": "set_timeline_paused",
  "paused": true,
  "wall_time_ms": 91235000
}
```

## Python API

```python
from rpg_engine.models import WorldState
from rpg_engine.timeline import TimeMode, TimelineItemKind, TimelineScheduler

world = WorldState(campaign_id="example", seed=42)
scheduler = TimelineScheduler(world)
scheduler.configure(TimeMode.HYBRID)
scheduler.schedule(
    "npc:smith:opens",
    TimelineItemKind.NPC_SCHEDULE,
    delay_ms=60_000,
    actor_id="smith",
)
result = scheduler.advance(60_000)
assert result.fired[0].item.id == "npc:smith:opens"
```

For authoritative event-sourced execution, use `TimelineSimulationEngine` or `CampaignService`
rather than mutating a scheduler outside the engine command boundary.
