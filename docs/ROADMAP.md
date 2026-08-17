# Roadmap

## v1.0 status

The original v0.x roadmap has converged into the **v1.0 RPG Platform** line.

### v0.1 — Core Simulation — implemented

Typed entities/components, deterministic RNG, commands/events, generic rules runtime, persistence,
async authority service and basic API.

### v0.2 — Tactical RPG — implemented

Encounters, initiative, action economy, typed resolutions/modifiers, reactions, saving throws,
effects, concentration/resources, damage traits and renderer-neutral spatial targeting.

### v0.3 — Adventure Engine — implemented

World graph, exploration/discovery, NPC templates, containers/equipment, dialogue, quests,
merchants and travel.

### v0.4 — Living World — implemented

First-class deterministic time, calendar, weather, NPC schedules, factions/reputation, settlement
economy, off-screen encounters, rumors/dynamic quests and resource ecology.

### v0.5 — Multiple Frontends — implemented and converged in v1.0

CLI, Textual TUI, browser client, versioned REST/OpenAPI, resumable WebSockets, observation API and
authenticated SSH terminal transport.

### v0.6 — Visual Adapters — implemented and converged in v1.0

Godot 2D/3D reference adapters, visual snapshots, scene/asset bindings and non-authoritative
movement/animation/VFX/audio presentation hints.

### v0.7 — AI Game Master — implemented

Filtered actor observations, async provider/narrator contracts, deterministic utility/behavior-tree
agents, NPC memory, validated encounter/quest proposals and offline evaluation.

### v0.8 — Multiplayer — implemented and converged in v1.0

Authenticated players, campaign membership, parties, spectators, optimistic/idempotent commands,
resumable events, rate limits and horizontal campaign placement primitives.

### v0.9 — Creator Platform — implemented and converged in v1.0

Content SDK/schema tools, campaign/map/creature/item/effect editing, rules plugin SDK, validation,
mod dependency/version constraints and local browser creator.

## v1.0 — RPG Platform — implemented

- stable engine/rules/content API version declarations
- stable `EngineSession` Python facade and published contract schemas
- stable local and hosted v1 API wrappers
- authenticated hosted campaigns from the v0.8 authority layer
- client release/artifact manifests with compatibility and SHA-256 integrity metadata
- community content release registry
- read-only public distribution API
- optional marketplace listing metadata, disabled by default
- unified CLI exposing local/TUI/SSH, hosted, creator and distribution workflows
- convergence of previously parallel v0.5/v0.6, v0.8 and v0.9 histories onto the v1 line

## Post-1.0 candidates

Future 1.x work can deepen capabilities without breaking v1 contracts:

- verified release signing and provenance
- richer spatial occupancy/collision/LOS/cover/pathfinding
- rewind/branching campaign timelines and state-hash verification
- distributed placement coordination and external auth providers
- community registry federation and moderation metadata
- packaged native client release automation
- AI provider adapters and richer deterministic evaluation
