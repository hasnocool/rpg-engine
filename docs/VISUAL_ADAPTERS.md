# v0.6 Visual Adapters

v0.6 adds renderer adapters without moving presentation authority into the simulation. The engine
continues to decide game state; renderers receive a viewer-scoped visual snapshot plus optional
presentation hints derived from persisted events.

## Target runtime

The reference Godot adapter targets **Godot 4.7.x**. Godot 4.7.1 is the stable release used as the
compatibility baseline for this milestone. The adapter intentionally avoids 4.8 development-only
APIs.

## Visual contract

`VisualSnapshot` is derived from `CampaignObservation`, so it inherits viewer filtering. Hidden
connections which the viewer has not discovered do not suddenly appear because a graphical client
is connected.

A snapshot contains:

- campaign and event sequence
- current logical location
- optional 2D and 3D scene bindings
- renderer-neutral actor positions
- optional per-actor 2D/3D asset bindings
- terminal glyphs
- known exits

The snapshot is not stored as authoritative state. It can always be rebuilt from the current world,
content pack, viewer, and visual binding manifest.

## Presentation hints

Authoritative events can be mapped to `PresentationBatch` objects containing optional hints:

- `movement_interpolation`
- `animation`
- `vfx`
- `audio`

These hints are explicitly non-authoritative. Ignoring an animation, choosing another easing curve,
or playing different audio cannot alter the campaign state.

The presentation WebSocket is resumable with the same persisted event sequence used by v0.5:

```text
WS /api/v1/campaigns/{id}/presentation/ws?after=N
```

The server replays presentation batches derived from persisted events after `N`, then waits for new
persisted events. Heartbeats do not advance the cursor.

## Asset and scene bindings

Bindings live in a separate YAML manifest rather than in rules code. See
`clients/godot/bindings.example.yaml`.

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

The Python service treats `res://...` strings as opaque renderer data. It never opens Godot assets.

## API

v0.6 adds these endpoints without changing the existing v1 state/event endpoints:

```text
GET /api/v1/campaigns/{id}/visual?actor_id=hero
GET /api/v1/campaigns/{id}/presentation?after=N
WS  /api/v1/campaigns/{id}/presentation/ws?after=N
```

Commands still use:

```text
POST /api/v1/campaigns/{id}/commands
```

The visual client therefore cannot bypass engine validation.

## Godot 2D

Copy `clients/godot/addons/rpg_engine` into a Godot 4.7 project and enable the plugin. Add an
`RPGApiClient` and `RPGVisualBridge2D` to your client scene, then connect:

```gdscript
api.visual_received.connect(bridge.apply_snapshot)
api.presentation_received.connect(bridge.apply_presentation)
api.request_visual("demo", "hero")
api.connect_presentation("demo", 0)
```

`RPGVisualBridge2D`:

- instantiates actor scenes from the binding manifest
- falls back to a tiny label marker if an actor scene is absent
- maps logical x/y positions into configurable pixels-per-unit
- tweens movement hints
- forwards named animations to an `AnimationPlayer` child
- can instantiate 2D VFX scenes and play positional audio bindings

The host project owns camera behavior, navigation visuals, lighting, art, and scene transitions.
`scene_requested` is emitted when the logical location requests another scene.

## Godot 3D

`RPGVisualBridge3D` follows the same contract and maps x/y/z to `Node3D.position`. It supports actor
scene instantiation, movement tweens, `AnimationPlayer`, 3D VFX scenes, and positional audio.

Because both bridges consume the same API data, a 2D and a 3D client can observe the same campaign
without changing simulation logic.

## SSH / terminal visual renderer

v0.6 also makes terminal/SSH a renderer target. The shared terminal protocol adds:

```text
map [actor_id]
visual [actor_id]
```

The command asks the same `CampaignClient.visual()` method used by other adapters and renders the
returned `VisualSnapshot` as ASCII. An SSH session therefore gets a logical map without accessing
raw SQLite state or a host shell.

When `serve-ssh` or `serve-all` is given `--visual-bindings`, terminal titles and glyphs come from
the same manifest used by Godot.

## Running

API/Godot service:

```bash
rpg-engine serve \
  --database rpg_engine.db \
  --content content/core \
  --visual-bindings clients/godot/bindings.example.yaml
```

Shared API + SSH authority:

```bash
rpg-engine serve-all \
  --database rpg_engine.db \
  --content content/core \
  --visual-bindings clients/godot/bindings.example.yaml \
  --host-key ssh_host_key \
  --authorized-keys authorized_keys
```

The visual manifest is optional. Without one, logical coordinates and terminal fallbacks still work,
while Godot asset paths remain empty.
