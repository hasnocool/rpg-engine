# rpg-engine

A **headless, deterministic, event-driven RPG simulation engine** for Python 3.12+.

The authoritative simulation is presentation-agnostic. CLI, TUI, browser, SSH terminal, web API,
2D, 3D, AI, and multiplayer clients issue the same commands and consume the same immutable events.

> The built-in `d20` runtime and `content/core` pack are original generic examples. This repository
> does not bundle proprietary tabletop rulebooks or copyrighted campaign content. Licensed,
> SRD-compatible, original, or homebrew rules/content belong in separate plugins and packs.

## Current milestone: v0.5 Multiple Frontends

v0.5 is implemented on top of the v0.3 Adventure Engine while v0.4 Living World remains a planned
simulation-depth milestone. The frontend milestone is intentionally independent of the future living
world systems.

v0.5 adds:

- interactive asynchronous CLI
- Textual TUI adapter
- browser reference client
- stable versioned `/api/v1` REST/OpenAPI contract
- resumable WebSocket event subscriptions using persisted event cursors
- renderer-neutral observation/query API
- authenticated AsyncSSH terminal transport
- shared `serve-all` mode for API + SSH on one authority service
- compatibility aliases for the original unversioned API

The core engine still knows nothing about pixels, terminal colors, browser layout, SSH, or input
devices. Those concerns live entirely in adapters.

## Architecture

```text
                       GAME CLIENTS / TRANSPORTS

     CLI          TUI          Browser          SSH terminal
      |            |              |                  |
      +------------+------ REST / WebSocket --------+
                             or local client
                                   |
                                   v
+----------------------------------------------------------------+
| CampaignService                                                |
| async per-campaign authority + resumable persisted event feed   |
| +------------------------------------------------------------+ |
| | SimulationEngine                                           | |
| | + Tactical systems                                         | |
| | + AdventureRuntime                                         | |
| | + Rules / Hooks / deterministic RNG                        | |
| +----------------------------+-------------------------------+ |
+------------------------------|---------------------------------+
                               | Events
                               v
                       SQLite event log
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

Deterministic demo:

```bash
rpg-engine demo --seed 918392482
```

REST/WebSocket/browser server:

```bash
rpg-engine serve --host 127.0.0.1 --port 8000
```

Interactive terminal client:

```bash
rpg-engine play --server http://127.0.0.1:8000 --campaign demo
```

Textual TUI:

```bash
rpg-engine tui --server http://127.0.0.1:8000 --campaign demo
```

The browser reference client is served at `/client` by the API process.

## SSH terminal

v0.5 can expose the RPG terminal protocol through a normal SSH client. The SSH endpoint is not an
operating-system shell and does not execute arbitrary host commands.

```bash
rpg-engine serve-ssh \
  --host 127.0.0.1 \
  --port 8022 \
  --host-key ssh_host_key \
  --authorized-keys authorized_keys \
  --campaign demo
```

Then connect with a standard SSH client:

```bash
ssh -p 8022 player@127.0.0.1
```

When REST/WebSocket/browser and SSH should operate on the same live campaigns, use the shared
single-process authority mode:

```bash
rpg-engine serve-all \
  --api-host 127.0.0.1 --api-port 8000 \
  --ssh-host 127.0.0.1 --ssh-port 8022 \
  --host-key ssh_host_key \
  --authorized-keys authorized_keys
```

See [`docs/FRONTENDS.md`](docs/FRONTENDS.md) for the transport model and terminal protocol.

## Stable API v1

New clients should use:

```text
GET  /api/v1/health
POST /api/v1/campaigns
GET  /api/v1/campaigns/{id}/state
GET  /api/v1/campaigns/{id}/observation
GET  /api/v1/campaigns/{id}/events?after=N
POST /api/v1/campaigns/{id}/commands
WS   /api/v1/campaigns/{id}/events/ws?after=N
```

WebSocket subscriptions resume from a persistent event sequence. A client which last processed
sequence 418 can reconnect with `?after=418`; the service replays stored events 419 onward before
waiting for new events. This does not depend on an in-memory broadcast buffer.

## Renderer-neutral observations

`CampaignObservation` gives frontends a logical view rather than forcing them to render raw
`WorldState`. A viewer-specific observation can contain:

- current logical location and known exits
- co-located actors
- encounter round/active actor/action budget summary
- quest progress
- active dialogue sessions
- equipment and currency summaries

Hidden world connections stay absent until the viewer has discovered them.

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

Randomness uses named counter-based streams:

```text
campaign seed + stream name + stream counter -> deterministic roll
```

Adventure search and dialogue checks use the same modifier/provenance pipeline as tactical d20
resolution. Events preserve the post-command RNG counters.

Adventure events also preserve enough resulting state to replay historical decisions without
re-running current content rules. For example, a commerce event stores the actual historical price,
transferred quantity, and resulting inventories/balances. Changing a merchant price tomorrow does
not rewrite yesterday's event history.

v0.5 extends that replay property to client connectivity: event subscriptions are cursor-based and
read from persistence, so presentation clients may disconnect without changing simulation results.

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
|- api/              # stable v1 REST/OpenAPI + resumable WebSocket adapter
|- clients/          # local and async HTTP client adapters
|- content/          # content schemas/loaders
|- persistence/      # async event/snapshot storage
|- rules/            # ruleset interface + generic d20 runtime
|- adventure.py      # v0.3 world/dialogue/quest/inventory/economy authority
|- observations.py   # renderer-neutral v0.5 query models
|- terminal.py       # shared CLI/TUI/SSH terminal protocol
|- tui.py            # Textual presentation adapter
|- ssh_server.py     # authenticated AsyncSSH RPG transport
|- webclient.py      # embedded browser reference client
|- commands.py       # intent contracts
|- events.py         # immutable facts
|- models.py         # persistent world/entity/tactical/adventure state
|- resolution.py     # modifier pipeline + typed outcomes
|- spatial.py        # tactical grid/graph movement/targeting contracts
|- hooks.py          # trigger/reaction extension contracts
|- effects.py        # composable effect execution
|- engine.py         # authoritative command processor
|- reducer.py        # replay reconstruction
|- service.py        # async concurrency/persistence/event-stream boundary
`- cli.py            # process entrypoints

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

## Roadmap

See [`docs/ROADMAP.md`](docs/ROADMAP.md).

v0.5 Multiple Frontends is implemented out of sequence because it is transport/presentation work.
The next unimplemented simulation-depth milestone remains **v0.4 Living World**: calendar scheduling,
weather, NPC schedules, factions/reputation, settlement economy, off-screen encounter resolution,
rumors/dynamic quests, and regeneration/ecology hooks.
