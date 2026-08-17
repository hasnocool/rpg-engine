# rpg-engine

A **headless, deterministic, event-driven tabletop RPG simulation engine** for Python 3.12+.

The authoritative simulation is presentation-agnostic. CLI, TUI, web, Discord, 2D, 3D, AI, and
multiplayer clients issue the same commands and consume the same immutable events.

> The built-in `d20` runtime is a generic example ruleset. This repository does not bundle
> proprietary tabletop rulebooks or copyrighted game content. Licensed, SRD-compatible, original,
> or homebrew rules/content belong in separate ruleset plugins and content packs.

## Current milestone: v0.2 Tactical RPG

v0.2 builds a tactical authority layer on the deterministic v0.1 core:

- persisted encounter aggregates with deterministic initiative ordering
- round/turn cursor and authoritative active-actor validation
- action, bonus-action, reaction, and movement budgets
- typed d20 resolution contexts/outcomes
- modifier pipelines with source/provenance audit trails
- saving throws
- trigger/reaction hook contracts and persisted reaction windows
- generic resource pools and concentration state
- resistance, immunity, and vulnerability damage transforms
- timed effects with deterministic expiry
- single-target and area-targeting contracts
- grid and graph spatial adapter interfaces
- event-replay reconstruction of tactical state
- v0.1 command compatibility outside active encounters

The engine still knows nothing about pixels, meshes, terminal colors, WebGL, cameras, or input
devices.

## Architecture

```text
Human / AI / Client
        |
      Command
        v
+---------------------------+
| CampaignService           | async per-campaign authority
| +-----------------------+ |
| | SimulationEngine      | |
| | encounters / rules    | |
| | effects / hooks / RNG | |
| +-----------+-----------+ |
+-------------|-------------+
              | Events
      +-------+---------+
      |                 |
 SQLite/event log   WebSocket/UI
```

Rules and geometry remain replaceable contracts:

```text
SimulationEngine
  |- RulesRuntime
  |    |- d20 reference runtime
  |    `- custom rulesets
  |
  |- SpatialAdapter
  |    |- GridSpatialAdapter
  |    `- GraphSpatialAdapter
  |
  `- HookRegistry
       `- ruleset/content reaction hooks
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

Roll a saving throw:

```json
{
  "type": "roll_saving_throw",
  "actor_id": "fighter-1",
  "ability": "dexterity",
  "dc": 13,
  "source_id": "trap-1"
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

## Determinism

Randomness uses named counter-based streams:

```text
campaign seed + stream name + stream counter -> deterministic roll
```

The counters are state, and events preserve post-command counter state. Snapshot + event replay
therefore restores both the visible world and the future RNG position.

Initiative ordering is deterministic too: total descending, modifier descending, actor ID ascending.

## Tactical authority

Inside an active encounter:

- only the active actor may spend action, bonus-action, or movement budget
- reactions may be spent out of turn only from an authoritative reaction window
- weapon/effect range is validated by the configured spatial adapter
- movement cost is computed by the spatial adapter, never trusted from the client
- resource costs are checked and spent atomically before effects resolve
- damage traits are applied before HP mutation
- timed effects and concentration are stateful and event-sourced

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

## Repository layout

```text
src/rpg_engine/
|- api/              # FastAPI + WebSocket adapter
|- content/          # data-driven content schemas/loaders
|- persistence/      # async event/snapshot storage
|- rules/            # ruleset interface + generic d20 runtime
|- commands.py       # intent contracts
|- events.py         # immutable facts
|- models.py         # world/entity/encounter state
|- resolution.py     # modifier pipeline + typed outcomes
|- spatial.py        # grid/graph targeting/movement contracts
|- hooks.py          # trigger/reaction extension contracts
|- effects.py        # composable effect execution
|- engine.py         # authoritative processor
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

See [`docs/ROADMAP.md`](docs/ROADMAP.md). The next milestone is **v0.3 Adventure Engine**:
graph-based world transitions, exploration/discovery, inventory containers/equipment, dialogue,
quests, merchants, NPC templates, and travel.
