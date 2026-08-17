# rpg-engine

A **headless, deterministic, event-driven RPG simulation engine** for Python 3.12+.

The authoritative simulation is presentation-agnostic. CLI, TUI, web, Discord, 2D, 3D, AI, and
multiplayer clients issue the same commands and consume the same immutable events.

> The built-in `d20` runtime and `content/core` pack are original generic examples. This repository
> does not bundle proprietary tabletop rulebooks or copyrighted campaign content. Licensed,
> SRD-compatible, original, or homebrew rules/content belong in separate plugins and packs.

## Current milestone: v0.3 Adventure Engine

v0.3 adds a persistent adventure layer on top of the v0.1 deterministic core and v0.2 tactical
runtime:

- graph-based world locations and travel connections
- hidden connections and actor-specific discovery knowledge
- deterministic exploration and location search checks
- data-driven NPC templates
- persistent containers, looting, equipment slots, and currency
- dialogue graphs with requirements and d20 checks
- event-sourced quest state machines
- data-driven merchant profiles and authoritative buy/sell transactions
- replay-safe travel, commerce, dialogue, inventory, knowledge, and quest state
- compatibility with all v0.1/v0.2 commands

The engine still knows nothing about pixels, meshes, terminal colors, cameras, WebGL, or input
devices.

## Architecture

```text
Human / AI / Client
        |
      Command
        v
+--------------------------------+
| CampaignService                | async per-campaign authority
| +----------------------------+ |
| | SimulationEngine           | |
| | + Tactical systems         | |
| | + AdventureRuntime         | |
| | + Rules / Hooks / RNG      | |
| +-------------+--------------+ |
+---------------|----------------+
                | Events
        +-------+---------+
        |                 |
 SQLite/event log   WebSocket/UI
```

The world itself is content-driven:

```text
Location ---- Connection ---- Location
   |                           |
Discovery                    NPC template
   |                           |
Container                 Dialogue / Merchant
                               |
                              Quest
```

Renderers can attach coordinates, scenes, sprites, meshes, or maps without changing the logical
world graph.

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

Commands work through the same REST and WebSocket interfaces introduced in v0.1.

## Adventure command examples

Explore the actor's current logical location:

```json
{
  "type": "explore_location",
  "actor_id": "fighter-1"
}
```

Search for hidden content:

```json
{
  "type": "search_location",
  "actor_id": "fighter-1",
  "ability": "wisdom"
}
```

Travel over an authoritative world connection:

```json
{
  "type": "travel",
  "actor_id": "fighter-1",
  "destination_id": "forest"
}
```

Spawn an NPC from content:

```json
{
  "type": "spawn_npc",
  "template_id": "blacksmith",
  "entity_id": "torvald",
  "location_id": "village"
}
```

Start a conversation:

```json
{
  "type": "start_dialogue",
  "actor_id": "fighter-1",
  "npc_id": "torvald"
}
```

Buy from an authoritative merchant inventory:

```json
{
  "type": "buy_item",
  "actor_id": "fighter-1",
  "merchant_id": "torvald",
  "item_id": "longsword",
  "quantity": 1
}
```

## Determinism and replay

Randomness still uses named counter-based streams:

```text
campaign seed + stream name + stream counter -> deterministic roll
```

Adventure search and dialogue checks use the same modifier/provenance pipeline as tactical d20
resolution. Events preserve the post-command RNG counters.

Adventure events also preserve enough resulting state to replay historical decisions without
re-running current content rules. For example, a commerce event stores the actual historical price,
transferred quantity, and resulting inventories/balances. Changing a merchant price tomorrow does
not rewrite yesterday's event history.

## World graph and discovery

`WorldLocationSpec` and `WorldConnectionSpec` define the logical world independently of rendering.
Connections can be bidirectional, timed, tagged, and hidden.

Hidden connections are unusable until an authoritative discovery reveals them. Knowledge is stored
per actor:

```text
locations
connections
discoveries
containers
```

A search command performs one deterministic d20 resolution and can reveal every matching discovery
whose DC is met. Discoveries can reveal locations, graph connections, and loot containers.

## NPCs, dialogue, and quests

NPCs are instantiated from data-driven templates. Templates can bind an entity to a dialogue graph
and merchant profile.

Dialogue options can include:

- quest-state requirements
- d20 checks with success/failure branches
- quest start actions
- quest transition triggers
- explicit conversation termination

Quests are state machines with declared states and trigger-driven transitions. Invalid transitions
are rejected by the authoritative engine rather than being invented by a client or narrator.

## Inventory and economy

v0.3 adds:

- persistent container state
- authoritative loot transfer
- equipment slots with equip/unequip events
- item values and tags
- per-entity currency balances
- merchant stock and funds
- buy/sell multipliers and price overrides
- exact transaction snapshots for event replay

Adventure inventory/commerce actions are rejected during active tactical encounters so they cannot
bypass v0.2 action economy.

## Content remains data-driven

A world connection is ordinary YAML:

```yaml
id: village_forest
from_location_id: village
to_location_id: forest
travel_minutes: 30
bidirectional: true
hidden: false
```

A quest is also data:

```yaml
id: northern_road
name: Clear the Northern Road
initial_state: offered
states: [offered, investigating, ready_to_report, complete]
terminal_states: [complete]
transitions:
  - from_state: offered
    trigger: accept
    to_state: investigating
```

The included core examples provide a tiny original village/forest/ruins loop, a blacksmith NPC,
merchant inventory, dialogue, discoveries, containers, and a quest for automated testing.

## Repository layout

```text
src/rpg_engine/
|- api/              # FastAPI + WebSocket adapter
|- content/          # content schemas/loaders
|- persistence/      # async event/snapshot storage
|- rules/            # ruleset interface + generic d20 runtime
|- adventure.py      # v0.3 world/dialogue/quest/inventory/economy authority
|- commands.py       # intent contracts
|- events.py         # immutable facts
|- models.py         # persistent world/entity/tactical/adventure state
|- resolution.py     # modifier pipeline + typed outcomes
|- spatial.py        # tactical grid/graph movement/targeting contracts
|- hooks.py          # trigger/reaction extension contracts
|- effects.py        # composable effect execution
|- engine.py         # authoritative command processor
|- reducer.py        # replay reconstruction
|- service.py        # async concurrency/persistence boundary
`- cli.py            # text adapter

content/core/
|- world/            # locations, connections, discoveries
|- npcs/
|- dialogue/
|- quests/
|- merchants/
|- containers/
|- items/
`- effects/
```

## Test

```bash
ruff check .
pytest --cov=rpg_engine --cov-report=term-missing
```

## Next milestone

See [`docs/ROADMAP.md`](docs/ROADMAP.md). The next milestone is **v0.4 Living World**: calendar
scheduling, weather, NPC schedules, factions/reputation, settlement economy, off-screen encounter
resolution, rumors/dynamic quests, and regeneration/ecology hooks.
