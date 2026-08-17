# Living World Runtime — v0.4

v0.4 turns the v0.3 adventure map into a world that continues to change through the same
deterministic, event-sourced authority used for combat, travel, dialogue, and quests.

## First-class time

The world owns one persisted timeline. It supports:

- `turn_based`
- `timed_turn_based`
- `real_time`
- `real_time_with_pause`
- `hybrid`

Logical time is integer milliseconds. The scheduler never sleeps and never reads a process clock.
Real-time advancement receives an explicit monotonic timestamp from the caller, which makes it
replayable. Recurring work is bounded by `max_firings`; overdue work remains as a backlog instead of
monopolizing the campaign authority loop.

The same queue is used for actor readiness, delayed actions, spell completion, condition ticks,
world jobs, NPC schedules, reaction windows, idle pressure, and custom jobs.

## Calendar

A data-driven calendar translates absolute timeline minutes into year, day, minute-of-day, and
season. `CalendarAdvancedEvent` records the derived result, so replay does not need to infer past
calendar state from current content.

## Weather

Weather profiles belong to logical regions and contain weighted conditions plus temperature,
precipitation, and wind ranges. Weather updates use named deterministic RNG streams and recur on the
authoritative timeline.

## NPC schedules

NPC templates may reference an `NpcScheduleSpec`. Schedule entries map minute-of-day to a location
and activity. Scheduled movement updates logical `Position` only and is skipped while an NPC is in
an active tactical encounter. Renderers remain free to animate the transition however they want.

## Factions and reputation

Faction-to-faction relationships and actor-to-faction reputation use bounded `[-100, 100]` scores.
Changes are symmetric for faction relations and always emit the previous/current values plus a
reason for auditability.

## Settlement economy

Settlements have population, treasury, prosperity, stocks, production, consumption, income, and
expenses. Recurring economy jobs update stocks, scarcity-derived price indices, treasury, and
prosperity. The system is intentionally primitive but event-sourced and content-driven so later
trade routes, taxes, crafting, and market simulation can build on stable state.

## Off-screen encounters

`resolve_offscreen_encounter` provides deterministic coarse conflict resolution for actors that are
not in an active tactical encounter. It scores each side from current entity state plus named RNG,
applies bounded attrition, and stores a complete `OffscreenEncounterRecord`. It does not pretend to
simulate tactical turns that never occurred.

## Rumors and dynamic quests

Rumor templates can recur as world jobs and optionally create dynamic quests. Generated quests
select their target deterministically, carry an expiry timestamp, and can award authoritative
currency rewards when completed at the target location. Expiry is processed as time advances.

## Resource regeneration and ecology hooks

Resource nodes represent renewable world resources with capacity, current quantity, and recurring
regeneration. Harvesting is authoritative and transfers real item IDs into actor inventory.

`EcologyHookRegistry` allows deterministic rulesets/content extensions to modify regeneration based
on node state, weather, or world state without placing game-specific ecology math in the core.

## Replay

Every v0.4 mutation has an immutable event and reducer path, including timeline scheduling/firing,
calendar, weather, NPC positions, faction/reputation state, settlement economy, off-screen results,
rumors, generated quests, rewards, harvesting, and regeneration.

Snapshot + subsequent events therefore reconstruct both visible state and the future timeline/RNG
position.
