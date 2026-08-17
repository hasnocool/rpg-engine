# rpg-engine 1.0

`rpg-engine` is a headless, deterministic, event-sourced tabletop RPG platform for Python 3.12+.

Version **1.0.0** converges the previously parallel simulation, multiplayer, frontend/visual, AI,
and creator-platform tracks into one supported platform line.

The engine remains authoritative and presentation-neutral:

```text
                   commands
CLI / TUI / Web / SSH / Godot / AI
                     |
                     v
+--------------------------------------------------+
| CampaignService / HostedCampaignService          |
| SimulationEngine                                 |
| tactical + adventure + living world + AI runtime |
| deterministic RNG + immutable events + replay    |
+--------------------------+-----------------------+
                           |
                    SQLite event log
```

The bundled generic d20 runtime and example content are original project examples. Proprietary
tabletop books or campaign text are not bundled.

## Stable v1 contracts

The following surfaces are public for the 1.x line:

- `rpg_engine.public.EngineSession`
- typed `Command` and immutable `Event` contracts
- `WorldState` and content schemas
- content-pack format and Creator Platform schemas
- rules plugin API version `1`
- local REST/WebSocket `/api/v1` contracts
- hosted multiplayer `/v1` contracts
- public platform/distribution `/v1` contracts

Breaking changes to these contracts require a new engine major version. Additive fields and new
commands/events may be added in compatible 1.x releases.

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Play and host

```bash
rpg-engine demo
rpg-engine serve
rpg-engine serve-hosted --port 8001
rpg-engine play --campaign CAMPAIGN_ID
rpg-engine tui --campaign CAMPAIGN_ID
rpg-engine serve-ssh --port 8022
```

SSH is an RPG protocol endpoint, not an operating-system shell.

## Creator Platform

```bash
rpg-engine creator init ./my-pack --id my_pack --name "My Pack"
rpg-engine creator new ./my-pack location village --name "Village"
rpg-engine creator validate ./my-pack
rpg-engine creator serve ./my-pack
```

New v1 workspaces default to the engine constraint `>=1,<2`.

## Public Python API

```python
from rpg_engine.public import EngineSession

session = EngineSession.create(seed=42, campaign_id="demo")
events = session.execute({
    "type": "advance_time",
    "minutes": 10,
})
state = session.state
```

`rpg_engine.public.public_contract_schemas()` exposes JSON Schema for commands, events, world state,
content, and rules-plugin descriptors.

## Community distribution

v1 includes a local/admin-managed release registry and a read-only public API.

```bash
rpg-engine platform init
rpg-engine platform publish-client client-release.yaml
rpg-engine platform publish-content content-release.yaml
rpg-engine platform serve --port 8080
```

A client release records platform/architecture, download URL, SHA-256, engine compatibility, and
release channel. Content releases record the same compatibility/integrity information plus
license/tags/dependencies.

The registry resolves the highest compatible release and exposes redirect endpoints for downloads.
It does not silently download or execute artifacts.

## Optional creator marketplace

Marketplace support is **metadata-only and disabled by default**. A listing can reference a
published content release, publisher, license, price metadata, tags, and an optional external
checkout URL. `rpg-engine` does not process payments or store payment credentials.

## Visual adapters and clients

The repository includes terminal/CLI, Textual TUI, a browser reference client, authenticated SSH,
renderer-neutral observations/visual snapshots, Godot 2D/3D reference adapters, and resumable event
and presentation subscriptions.

See `docs/FRONTENDS.md` and `docs/VISUAL_ADAPTERS.md`.

## Simulation depth

The unified v1 line includes deterministic tactical encounters, adventure maps/dialogue/quests,
first-class time, living-world weather/schedules/factions/economy/ecology, AI provider/narrator
contracts and memory, plus authenticated multiplayer/parties/spectators/idempotent commands.

See `docs/TACTICAL.md`, `docs/ADVENTURE.md`, `docs/LIVING_WORLD.md`,
`docs/AI_GAME_MASTER.md`, and `docs/MULTIPLAYER.md`.

## Platform documentation

See `docs/PLATFORM.md`, `docs/CREATOR_PLATFORM.md`, and `docs/ROADMAP.md`.

## Test

```bash
ruff check .
pytest --cov=rpg_engine --cov-report=term-missing
```
