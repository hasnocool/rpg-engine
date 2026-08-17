# rpg-engine

A **headless, deterministic, event-driven RPG simulation engine** for Python 3.12+.

The authoritative simulation is presentation-agnostic. CLI, TUI, web, Discord, 2D, 3D, AI, and
multiplayer clients issue the same commands and consume the same immutable events.

> The built-in `d20` runtime and `content/core` pack are original generic examples. Proprietary
> tabletop rulebooks or campaign content are not bundled.

## Current milestone: v0.4 Living World

v0.4 builds on the v0.3 Adventure Engine and makes time and off-screen world change authoritative:

- one deterministic first-class timeline with five time policies
- calendar/seasons and recurring scheduled world jobs
- deterministic regional weather
- schedule-driven NPC location/activity state
- faction relationships and actor reputation
- recurring settlement production/consumption/economy ticks
- deterministic coarse off-screen encounter resolution
- recurring rumors that can generate dynamic quests
- quest expiry and authoritative rewards
- renewable resource nodes, harvesting, regeneration, and ecology hooks
- event/reducer replay for all v0.4 state

The engine still knows nothing about pixels, meshes, terminal colors, cameras, WebGL, or input
devices.

## Architecture

```text
Human / AI / Client
        |
      Command
        v
+-------------------------------------+
| CampaignService                     | async per-campaign authority
| +---------------------------------+ |
| | SimulationEngine                | |
| | + Tactical engine              | |
| | + AdventureRuntime             | |
| | + TimelineScheduler            | |
| | + LivingWorldRuntime           | |
| | + Rules / Hooks / RNG          | |
| +----------------+----------------+ |
+------------------|------------------+
                   | Events
           +-------+---------+
           |                 |
    SQLite/event log   WebSocket/UI
```

The scheduler never sleeps or blocks an event loop. Real-time policies advance only from explicit
monotonic timestamps supplied by the caller, while recurring catch-up work is bounded per command.
Filesystem content loading remains wrapped in `asyncio.to_thread` for async server use.

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

## Initialize the living world

```json
{
  "type": "initialize_living_world"
}
```

Initialization materializes faction/settlement/resource state, chooses initial deterministic
weather, and schedules recurring economy, weather, NPC, rumor, and ecology jobs.

## First-class time

Supported policies:

```text
turn_based
timed_turn_based
real_time
real_time_with_pause
hybrid
```

Configure a hybrid timeline:

```json
{
  "type": "configure_timeline",
  "mode": "hybrid",
  "turn_quantum_ms": 6000,
  "turn_timeout_ms": 30000
}
```

The same queue carries actor readiness, delayed actions, spell completion, condition ticks, world
events, NPC schedules, reaction windows, and idle pressure.

## Living-world commands

Faction relation:

```json
{
  "type": "adjust_faction_relation",
  "faction_a_id": "riverdale",
  "faction_b_id": "road_raiders",
  "delta": 10,
  "reason": "temporary truce"
}
```

Generate a rumor/dynamic quest:

```json
{
  "type": "generate_rumor",
  "location_id": "village",
  "template_id": "road_raiders"
}
```

Harvest a renewable node:

```json
{
  "type": "harvest_resource",
  "actor_id": "fighter-1",
  "node_id": "moonleaf_patch",
  "amount": 2
}
```

Resolve a coarse off-screen conflict:

```json
{
  "type": "resolve_offscreen_encounter",
  "encounter_id": "road-skirmish-1",
  "attacker_ids": ["guard-1", "guard-2"],
  "defender_ids": ["raider-1"],
  "location_id": "forest"
}
```

## Determinism and replay

Randomness uses named counter-based streams:

```text
campaign seed + stream name + stream counter -> deterministic roll
```

Logical time, scheduled jobs, post-job recurrence, RNG counters, weather outcomes, settlement state,
off-screen results, generated quests, and ecology state are persisted through immutable events.
Snapshot + replay therefore restores both current state and future deterministic behavior.

## Data-driven v0.4 content

The example pack now includes:

```text
content/core/world/calendars/
content/core/weather/
content/core/schedules/
content/core/factions/
content/core/settlements/
content/core/dynamic_quests/
content/core/rumors/
content/core/ecology/
```

NPC templates may bind a schedule with `schedule_id`. Cross-file content validation rejects unknown
locations, factions, schedules, quest templates, regions, resource items, and other broken links at
load time.

See [`docs/LIVING_WORLD.md`](docs/LIVING_WORLD.md) for the detailed v0.4 contract and
[`docs/ADVENTURE.md`](docs/ADVENTURE.md) for v0.3 adventure systems.

## Test

```bash
ruff check .
pytest --cov=rpg_engine --cov-report=term-missing
```

## Next milestone

The next roadmap milestone is **v0.5 Multiple Frontends**: interactive CLI, Textual/Rich TUI,
browser reference client, stable observation/query APIs, and resumable event subscriptions.
