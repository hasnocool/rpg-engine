# rpg-engine

A **headless, deterministic, event-driven tabletop RPG simulation engine** for Python 3.12+.

The authoritative simulation is presentation-agnostic. CLI, TUI, web, Discord, 2D, 3D, AI, and
multiplayer clients issue the same commands and consume the same immutable events.

> The built-in `d20` runtime is a generic example ruleset. This repository does not bundle
> proprietary tabletop rulebooks or copyrighted game content. Licensed, SRD-compatible, original,
> or homebrew rules/content belong in separate ruleset plugins and content packs.

## Current milestone: v0.2.1 First-class Time

v0.2.1 builds a deterministic scheduling layer on the v0.2 tactical authority:

- one persisted timeline shared by tactical and world scheduling
- `turn_based`, `timed_turn_based`, `real_time`, `real_time_with_pause`, and `hybrid` policies
- integer-millisecond logical time with explicit monotonic wall-clock synchronization
- deterministic priority and insertion-order tie breaking
- bounded recurring-event catch-up so a large time jump cannot monopolize the authority loop
- actor readiness and idle-pressure timing integrated with encounter turns
- first-class item kinds for delayed actions, spell completion, condition ticks, world events, NPC
  schedules, reaction windows, and custom jobs
- timeline commands, immutable events, reducer replay, and snapshot persistence
- compatibility bridge from the existing `advance_time` command

The engine still knows nothing about pixels, meshes, terminal colors, WebGL, cameras, or input
devices.

See [`docs/TIME.md`](docs/TIME.md) for the complete scheduler contract.

## Architecture

```text
Human / AI / Client
        |
      Command
        v
+----------------------------------+
| CampaignService                  | async per-campaign authority
| +------------------------------+ |
| | TimelineSimulationEngine     | |
| | +--------------------------+ | |
| | | SimulationEngine         | | |
| | | encounters/rules/effects | | |
| | +--------------------------+ | |
| | TimelineScheduler            | |
| +---------------+--------------+ |
+-----------------|----------------+
                  | Events
          +-------+---------+
          |                 |
   SQLite/event log   WebSocket/UI
```

Rules, geometry, and time policy remain replaceable contracts:

```text
TimelineSimulationEngine
  |- SimulationEngine
  |    |- RulesRuntime
  |    |- SpatialAdapter
  |    `- HookRegistry
  |
  `- TimelineScheduler
       |- turn-based
       |- timed turn-based
       |- real-time
       |- real-time with pause
       `- hybrid
```

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Run

```bash
rpg-engine demo --seed 918392482
rpg-engine serve --host 127.0.0.1 --port 8000
```

## Tactical command examples

Start an encounter:

```json
{
  "type": "start_encounter",
  "encounter_id": "bridge-fight",
  "participant_ids": ["fighter-1", "goblin-1"]
}
```

Attack on the active turn:

```json
{
  "type": "attack_target",
  "attacker_id": "fighter-1",
  "target_id": "goblin-1",
  "weapon_id": "longsword"
}
```

End the current turn:

```json
{
  "type": "end_turn",
  "actor_id": "fighter-1",
  "encounter_id": "bridge-fight"
}
```

The same payloads work through REST or the campaign WebSocket command channel.

## Timeline command examples

Configure time policy:

```json
{
  "type": "configure_timeline",
  "mode": "hybrid",
  "turn_quantum_ms": 6000,
  "turn_timeout_ms": 30000
}
```

Schedule any game-time job on the same queue:

```json
{
  "type": "schedule_timeline_item",
  "item_id": "spell:mage-1:completion",
  "kind": "spell_completion",
  "delay_ms": 12000,
  "actor_id": "mage-1",
  "payload": {"spell_id": "example"}
}
```

Synchronize a real-time or hybrid campaign with a caller-supplied monotonic clock:

```json
{
  "type": "sync_timeline",
  "wall_time_ms": 91234567
}
```

The scheduler never sleeps and never reads the wall clock itself. That keeps the campaign authority
non-blocking and makes elapsed-time inputs replayable.

## Determinism

Randomness uses named counter-based streams:

```text
campaign seed + stream name + stream counter -> deterministic roll
```

The counters are state, and events preserve post-command counter state. Snapshot + event replay
therefore restores both the visible world and the future RNG position.

Timeline ordering is deterministic too: due time ascending, numeric priority ascending, insertion
order ascending, then item ID. Real-time progression is deterministic on replay because clients send
monotonic timestamps and the engine stores the resulting timeline events.

## Tactical authority

Inside an active encounter:

- only the active actor may spend action, bonus-action, or movement budget
- reactions may be spent out of turn only from an authoritative reaction window
- weapon/effect range is validated by the configured spatial adapter
- movement cost is computed by the spatial adapter, never trusted from the client
- resource costs are checked and spent atomically before effects resolve
- damage traits are applied before HP mutation
- timed effects and concentration are stateful and event-sourced
- encounter actor readiness and idle pressure use the first-class timeline

Outside an encounter, v0.1 commands remain usable without tactical budget requirements.

## Content remains data-driven

v0.2 content schemas support:

```yaml
id: focus_guard
name: Focus Guard
action_cost: bonus_action
duration_turns: 3
concentration: true
resource_costs:
  focus: 1
targeting:
  shape: single
  max_range: 0
operations:
  - type: add_condition
    condition: focused
```

Area effects use the same effect pipeline with a targeting contract rather than renderer geometry.
Timeline firings can be consumed by ruleset hooks and translated into domain-specific commands, so
future adventure/living-world systems do not need separate schedulers.

## Repository layout

```text
src/rpg_engine/
|- api/              # FastAPI + WebSocket adapter
|- content/          # data-driven content schemas/loaders
|- persistence/      # async event/snapshot storage
|- rules/            # ruleset interface + generic d20 runtime
|- commands.py       # intent contracts, including timeline commands
|- events.py         # immutable simulation + timeline facts
|- models.py         # world/entity/encounter state
|- timeline.py       # time modes, persisted queue, deterministic scheduler
|- temporal.py       # timeline-aware authoritative engine
|- resolution.py     # modifier pipeline + typed outcomes
|- spatial.py        # grid/graph targeting/movement contracts
|- hooks.py          # trigger/reaction extension contracts
|- effects.py        # composable effect execution
|- engine.py         # v0.2 tactical processor
|- reducer.py        # replay reconstruction
|- service.py        # async concurrency/persistence boundary
`- cli.py            # text adapter
```

## Test

```bash
ruff check .
pytest --cov=rpg_engine --cov-report=term-missing
```

## Next milestone

See [`docs/ROADMAP.md`](docs/ROADMAP.md). The next milestone remains **v0.3 Adventure Engine**:
graph-based world transitions, exploration/discovery, inventory containers/equipment, dialogue,
quests, merchants, NPC templates, and travel. Those systems can now build on the v0.2.1 timeline
instead of inventing their own clocks.
