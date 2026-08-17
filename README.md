# rpg-engine

A **headless, deterministic, event-driven RPG simulation engine** for Python 3.12+.

The authoritative simulation is presentation-agnostic. CLI, TUI, browser, SSH terminal, Godot 2D,
Godot 3D, web API, AI, and future multiplayer clients issue the same commands and consume the same
immutable events.

> The built-in `d20` runtime and `content/core` pack are original generic examples. This repository
> does not bundle proprietary tabletop rulebooks or copyrighted campaign content. Licensed,
> SRD-compatible, original, or homebrew rules/content belong in separate plugins and packs.

## Current milestone: v0.6 Visual Adapters

v0.6 is implemented on top of v0.5 while **v0.4 Living World remains planned**. Like v0.5, this is a
presentation-layer milestone which can be built without claiming future world-simulation features.

v0.6 adds:

- renderer-neutral `VisualSnapshot` models derived from viewer-scoped observations
- asset/scene/event binding manifests
- movement interpolation hints
- animation/VFX/audio binding hints which remain non-authoritative
- resumable presentation-hint REST/WebSocket feeds derived from persisted events
- Godot 4.7 2D reference adapter
- Godot 4.7 3D reference adapter
- SSH/terminal ASCII visual rendering from the same visual snapshot
- `map` and `visual` terminal commands
- optional shared visual bindings across API, Godot, local terminal, and SSH

The core engine still knows nothing about pixels, meshes, cameras, terminal colors, Godot scenes,
SSH, or input devices. Those concerns live entirely in adapters.

## Architecture

```text
                   AUTHORITATIVE SIMULATION

                       CampaignService
                             |
                     SimulationEngine
                  +----------+----------+
                  |                     |
              Tactical              Adventure
                  |                     |
                  +----------+----------+
                             |
                       immutable events
                             |
                         SQLite log
                             |
          +------------------+------------------+
          |                                     |
  CampaignObservation                      event cursor
          |                                     |
          v                                     v
    VisualSnapshot                     PresentationBatch
          |                            movement/animation/
          |                               VFX/audio hints
   +------+------+----------------+-------------+
   |             |                |             |
Godot 2D      Godot 3D       Terminal/SSH    future UI
```

`VisualSnapshot` and presentation hints are derived views. They are not authoritative state and do
not participate in deterministic replay decisions.

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Run the API / visual service

```bash
rpg-engine serve \
  --host 127.0.0.1 \
  --port 8000 \
  --database rpg_engine.db \
  --content content/core \
  --visual-bindings clients/godot/bindings.example.yaml
```

The visual binding manifest is optional. Without one, logical snapshots and terminal rendering still
work; Godot asset paths simply remain empty.

## API v1

Existing v0.5 endpoints remain intact:

```text
GET  /api/v1/health
POST /api/v1/campaigns
GET  /api/v1/campaigns/{id}/state
GET  /api/v1/campaigns/{id}/observation
GET  /api/v1/campaigns/{id}/events?after=N
POST /api/v1/campaigns/{id}/commands
WS   /api/v1/campaigns/{id}/events/ws?after=N
```

v0.6 adds:

```text
GET /api/v1/campaigns/{id}/visual?actor_id=hero
GET /api/v1/campaigns/{id}/presentation?after=N
WS  /api/v1/campaigns/{id}/presentation/ws?after=N
```

Presentation subscriptions use the same persisted event sequence cursor as the v0.5 event stream.
A renderer can disconnect and resume without losing presentation-relevant events.

## Godot 2D / 3D

The reference adapter targets **Godot 4.7.x**. Copy:

```text
clients/godot/addons/rpg_engine
```

into a Godot project and use:

- `RPGApiClient`
- `RPGVisualBridge2D`
- `RPGVisualBridge3D`

The API client fetches visual snapshots, subscribes to the resumable presentation WebSocket, and can
send normal engine commands. The bridges instantiate renderer-owned actor scenes, map logical
coordinates, tween movement, invoke named animations, and optionally instantiate VFX/audio assets.

A renderer may ignore or replace any presentation hint without changing campaign state.

See [`docs/VISUAL_ADAPTERS.md`](docs/VISUAL_ADAPTERS.md).

## Binding manifests

Renderer bindings are ordinary YAML and stay outside rules code:

```yaml
version: 1
scenes:
  village:
    scene_2d: res://world/village_2d.tscn
    scene_3d: res://world/village_3d.tscn
    terminal_title: Riverdale Village
actor_tags:
  hero:
    scene_2d: res://actors/hero_2d.tscn
    scene_3d: res://actors/hero_3d.tscn
    terminal_glyph: "@"
event_bindings:
  actor_moved:
    animation: walk
    interpolation_ms: 250
```

The Python service treats Godot resource paths as opaque strings. It never opens or executes assets.

## Terminal and SSH visual mode

The v0.5 terminal protocol remains available locally and over authenticated SSH. v0.6 adds:

```text
map [actor_id]
visual [actor_id]
```

Both commands request `CampaignClient.visual()` and render the returned `VisualSnapshot` as ASCII.
The SSH transport therefore becomes another renderer target rather than a special game-state path.

Standalone SSH server:

```bash
rpg-engine serve-ssh \
  --host 127.0.0.1 \
  --port 8022 \
  --database rpg_engine.db \
  --content content/core \
  --visual-bindings clients/godot/bindings.example.yaml \
  --host-key ssh_host_key \
  --authorized-keys authorized_keys \
  --campaign demo
```

Connect with a normal SSH client and run `map` or `visual`. The SSH endpoint remains an RPG protocol
server; it does not expose an operating-system shell, arbitrary subprocess execution, SFTP, or SCP.

For API/Godot and SSH on one live authority service:

```bash
rpg-engine serve-all \
  --database rpg_engine.db \
  --content content/core \
  --visual-bindings clients/godot/bindings.example.yaml \
  --host-key ssh_host_key \
  --authorized-keys authorized_keys
```

## Determinism and presentation

The simulation still uses deterministic named RNG streams and event sourcing. Visual state follows a
separate rule:

```text
authoritative world + viewer + bindings -> VisualSnapshot
persisted event + bindings             -> PresentationBatch
```

The renderer never feeds animation completion, frame timing, VFX state, audio playback, or camera
state back into the authoritative world. This keeps replay and multiplayer authority independent of
rendering speed and client type.

## Repository layout

```text
src/rpg_engine/
|- api/              # v1 REST/OpenAPI + resumable WebSocket adapters
|- clients/          # local and async HTTP client adapters
|- content/          # content schemas/loaders
|- persistence/      # async event/snapshot storage
|- rules/            # ruleset interface + generic d20 runtime
|- observations.py   # viewer-scoped logical observation models
|- visuals.py        # v0.6 visual snapshots/bindings/presentation hints
|- terminal_visual.py# ASCII renderer for the shared visual contract
|- terminal.py       # shared CLI/TUI/SSH terminal protocol
|- ssh_server.py     # authenticated AsyncSSH RPG transport
|- service.py        # async authority + event/visual query boundary
`- cli.py            # process entrypoints

clients/godot/
|- addons/rpg_engine/
|  |- rpg_api.gd
|  |- visual_bridge_2d.gd
|  `- visual_bridge_3d.gd
`- bindings.example.yaml
```

## Test

```bash
ruff check .
pytest --cov=rpg_engine --cov-report=term-missing
```

## Roadmap

See [`docs/ROADMAP.md`](docs/ROADMAP.md).

v0.5 and v0.6 are implemented out of sequence because they are presentation/transport work. The next
unimplemented **simulation-depth** milestone remains **v0.4 Living World**: calendar scheduling,
weather, NPC schedules, factions/reputation, settlement economy, off-screen encounter resolution,
rumors/dynamic quests, and regeneration/ecology hooks.
