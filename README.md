# rpg-engine

A **headless, deterministic, event-driven RPG simulation engine** for Python 3.12+.

The authoritative simulation is presentation-agnostic. CLI, TUI, web, Discord, 2D, 3D, AI, and
multiplayer clients issue the same commands and consume the same immutable events.

> The built-in `d20` runtime and `content/core` pack are original generic examples. Proprietary
> tabletop rulebooks or campaign content are not bundled.

## Current milestone: v0.8 Multiplayer

v0.8 adds a hosted multiplayer authority layer on top of the deterministic simulation and v0.7 AI
Game Master systems:

- authenticated player accounts and expiring sessions
- owner/player/spectator campaign roles
- controlled-actor assignments and campaign parties
- optimistic client command IDs with persisted idempotency receipts
- execution-lease fencing for abandoned in-flight commands
- reconnect/resume from persisted event cursors
- spectator read-only access and conservative player event filtering
- shared-database command/read/authentication rate limits
- horizontal node heartbeats, rendezvous placement, leases, redirects, and failover

The multiplayer layer coordinates **who may submit commands and how retries/reconnects are handled**.
It does not bypass `CampaignService`, `SimulationEngine`, rules, hooks, RNG, or the immutable event
log.

## Architecture

```text
Player / Spectator / AI / Client
              |
   bearer session + command ID
              v
+-------------------------------------+
| HostedCampaignService               |
| + auth / membership / parties       |
| + idempotency / rate limits         |
| + reconnect / spectator filtering   |
| + horizontal campaign placement     |
+------------------+------------------+
                   |
             typed Command
                   v
+-------------------------------------+
| CampaignService                     | async per-campaign authority
| +---------------------------------+ |
| | SimulationEngine                | |
| | + Tactical engine              | |
| | + AdventureRuntime             | |
| | + TimelineScheduler            | |
| | + LivingWorldRuntime           | |
| | + AIGameMasterRuntime          | |
| | + Rules / Hooks / RNG          | |
| +----------------+----------------+ |
+------------------|------------------+
                   | immutable Events
           +-------+---------+
           |                 |
    SQLite/event log   REST/WebSocket
```

The scheduler and hosted layer remain async-safe. PBKDF2 and the synchronous SQLite multiplayer
coordination operations run through `asyncio.to_thread`; heartbeat/reconnect waits use asyncio
primitives rather than blocking sleeps.

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Run local/development authority

```bash
rpg-engine demo --seed 918392482
rpg-engine serve --host 127.0.0.1 --port 8000
```

## Run the authenticated hosted multiplayer API

```bash
uvicorn rpg_engine.api.hosted:app --host 0.0.0.0 --port 8000
```

For a public deployment, put TLS in front of the hosted API and do not expose the legacy
unauthenticated development adapter directly to the Internet.

## Multiplayer command envelope

Hosted clients send their normal typed command inside an optimistic command envelope:

```json
{
  "client_command_id": "web-7f15c1a1",
  "command": {
    "type": "move_actor",
    "actor_id": "fighter-1",
    "position": {"area": "village"}
  }
}
```

The receipt key is `campaign_id + player_id + client_command_id`. A retry with the same canonical
command replays the stored authoritative result without executing it again. Reusing the client ID
for different intent is rejected.

Clients can reconcile an optimistic command after reconnect with:

```text
GET /v1/campaigns/{campaign_id}/commands/{client_command_id}
```

## Reconnect and resume

The event log remains the source of truth:

```text
GET /v1/campaigns/{campaign_id}/events?after=418
WS  /v1/campaigns/{campaign_id}/events/ws?after=418&token=...
```

The WebSocket first replays persisted events, then waits for new ones and emits heartbeat envelopes
without changing the event cursor. The global cursor advances across filtered/hidden events so a
player cannot become stuck replaying sequences they are not allowed to see.

## Horizontal placement

Each hosted node registers a unique `node_id` and routable `public_url`. Campaign ownership uses
rendezvous hashing over live nodes plus persisted leases and monotonically increasing placement
epochs. Expired nodes are removed from consideration and the next request deterministically fails
over to a surviving node.

Requests reaching a non-owner node receive HTTP 307 with the current placement. WebSocket clients
receive a redirect envelope and reconnect to the owning node.

The included `MultiplayerStore` is the SQLite reference coordination backend and is suitable for
multiple processes sharing a local WAL database. Multi-host production deployments should use a
shared coordination database with equivalent transactional semantics rather than SQLite over an
unsafe network filesystem.

## AI Game Master

AI providers receive `AiObservation` rather than raw `WorldState`. Hidden connections, remote
actors, unrelated inventories/resources, and other non-visible state are filtered before a provider
runs.

Reference implementations include `UtilityAgent`, `BehaviorTreeAgent`, and
`DeterministicNarrator`. `AIGameMasterCoordinator` is asynchronous and serializes turns for the same
actor without blocking the event loop.

AI encounter/quest proposals are validated and persisted before activation. Accepted encounter
proposals delegate to `StartEncounterCommand`; accepted quest proposals must reference a validated
dynamic quest template and delegate to `GenerateDynamicQuestCommand`.

## First-class time and Living World

The same deterministic first-class timeline carries tactical readiness, delayed actions, effects,
world events, NPC schedules, reaction windows, and idle pressure across these policies:

```text
turn_based
timed_turn_based
real_time
real_time_with_pause
hybrid
```

v0.4 Living World adds calendar/seasons, weather, NPC schedules, factions/reputation, settlement
economy, off-screen encounters, rumors/dynamic quests, and renewable ecology.

## Determinism and replay

Randomness uses named counter-based streams:

```text
campaign seed + stream name + stream counter -> deterministic roll
```

Game-state changes still flow through immutable events and reducers. Multiplayer sessions,
idempotency receipts, rate-limit counters, party records, and placement leases are hosting state and
are intentionally kept outside deterministic `WorldState`.

## Documentation

- [`docs/MULTIPLAYER.md`](docs/MULTIPLAYER.md) — v0.8 hosted multiplayer contract
- [`docs/AI_GAME_MASTER.md`](docs/AI_GAME_MASTER.md) — v0.7 AI authority contract
- [`docs/LIVING_WORLD.md`](docs/LIVING_WORLD.md) — v0.4 living-world systems
- [`docs/ADVENTURE.md`](docs/ADVENTURE.md) — v0.3 adventure systems
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — milestone sequencing

## Test

```bash
ruff check .
pytest --cov=rpg_engine --cov-report=term-missing
```

## Next milestone

The next roadmap milestone is **v0.9 Creator Platform**: content-pack SDK/schema tooling, editors,
rules plugin SDK, validation/lint tooling, and dependency/version constraints for mods.
