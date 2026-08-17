# rpg-engine

A **headless, deterministic, event-driven tabletop RPG simulation engine** for Python 3.12+.

The engine deliberately separates authoritative game state from presentation. A terminal client,
web app, Discord bot, 2D renderer, 3D renderer, AI narrator, or multiplayer server can all issue
the same commands and consume the same events without owning game rules.

> The built-in `d20` runtime is a generic example ruleset. This repository does not bundle
> proprietary tabletop rulebooks or copyrighted game content. Licensed, SRD-compatible, original,
> or homebrew content should live in separate content packs/ruleset plugins.

## Architecture

```text
Clients (CLI / TUI / Web / 2D / 3D / AI)
                    |
                 Commands
                    v
          +-------------------+
          | SimulationEngine  |
          | validation/rules  |
          | effects/state/RNG |
          +---------+---------+
                    |
                  Events
                    v
       +------------+-------------+
       | persistence / websocket  |
       | replay / UI / analytics  |
       +--------------------------+
```

The current v0.1 foundation includes:

- strict Pydantic command/event contracts
- deterministic named RNG streams whose counters are persisted in world state
- component-oriented entities (`Identity`, `Stats`, `Health`, `Position`, `Inventory`, conditions)
- a pluggable `RulesRuntime` interface with a generic d20 implementation
- data-driven YAML weapons and composable effect definitions
- attack/check/movement/effect/time commands
- immutable combat, damage, healing, condition, movement, and time events
- event reducers for reconstruction between snapshots
- async SQLite persistence using WAL mode and `aiosqlite`
- per-campaign async locks to serialize authoritative mutations safely
- FastAPI REST endpoints and WebSocket command/event transport
- a Typer CLI and deterministic combat demo
- CI across Python 3.12 and 3.13

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Run the deterministic demo

```bash
rpg-engine demo --seed 918392482
```

The same seed and command sequence produce the same dice results and state transitions.

## Run the authoritative API

```bash
rpg-engine serve --host 127.0.0.1 --port 8000
```

Create a campaign:

```bash
curl -X POST http://127.0.0.1:8000/campaigns \
  -H 'content-type: application/json' \
  -d '{"seed":918392482,"campaign_id":"demo"}'
```

Create an actor:

```bash
curl -X POST http://127.0.0.1:8000/campaigns/demo/commands \
  -H 'content-type: application/json' \
  -d '{
    "type":"create_entity",
    "entity":{
      "id":"fighter-1",
      "identity":{"name":"Aric","tags":["hero"]},
      "stats":{"strength":16,"armor_class":16},
      "health":{"current":24,"maximum":24},
      "position":{},
      "inventory":{},
      "conditions":[]
    }
  }'
```

Issue an attack command after adding a target:

```json
{
  "type": "attack_target",
  "attacker_id": "fighter-1",
  "target_id": "goblin-1",
  "weapon_id": "longsword"
}
```

Clients can also connect to:

```text
ws://127.0.0.1:8000/campaigns/{campaign_id}/ws
```

and send the same command JSON. Emitted events are broadcast to connected campaign clients.

## Core design rules

1. **The simulation core knows nothing about rendering.** No pixels, HTML, meshes, sprites,
   terminal colors, cameras, or controller input exist in the domain layer.
2. **Commands request; events record.** Players, humans, AIs, and remote clients can only request
   actions through commands.
3. **Rulesets answer mechanical questions.** Edition/system-specific math belongs behind
   `RulesRuntime`, not scattered through transport or rendering code.
4. **Content is data.** Items/effects are YAML now; creatures, spells, quests, dialogue, factions,
   maps, and schedules will follow the same model.
5. **RNG is explicit state.** Randomness is never drawn from Python's process-global PRNG.
6. **Persistence is append-first.** Events are authoritative history; snapshots accelerate load.
7. **Concurrency is serialized per campaign.** Concurrent clients cannot interleave state mutation.
8. **Narrators describe reality; they do not invent authoritative state.** Future LLM integration
   consumes observations/events and returns commands or prose, never direct state mutations.

## Repository layout

```text
src/rpg_engine/
├── api/              # FastAPI + WebSocket adapter
├── content/          # content schemas/loaders
├── persistence/      # event/snapshot stores
├── rules/            # ruleset interface + generic d20 runtime
├── commands.py       # intent contracts
├── dice.py           # deterministic named RNG streams
├── effects.py        # composable effect pipeline
├── engine.py         # authoritative command processor
├── events.py         # immutable facts
├── models.py         # entities/components/world state
├── reducer.py        # event reconstruction
├── service.py        # async concurrency/persistence boundary
└── cli.py            # text adapter

content/core/         # original example content pack
docs/                 # architecture and roadmap
tests/                # deterministic/core/persistence/API tests
```

## Test

```bash
ruff check .
pytest --cov=rpg_engine --cov-report=term-missing
```

## Roadmap

See [`docs/ROADMAP.md`](docs/ROADMAP.md). The next major milestone is **v0.2 Tactical RPG**:
encounters, initiative, action economy, reactions, conditions/hooks, richer effect targeting,
and spatial adapters without coupling the simulation to a renderer.
