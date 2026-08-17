# Roadmap

The project is intentionally staged so simulation depth is built before expensive presentation work.
Some presentation milestones can be implemented independently; their status is called out explicitly.

## v0.1 — Core Simulation (implemented)

- typed entities/components
- commands and immutable events
- deterministic named RNG streams
- generic d20 `RulesRuntime`
- checks and attacks
- data-driven weapons/effects
- conditions, healing, damage, time
- snapshots + event persistence
- async campaign authority service
- REST/WebSocket adapter
- CLI demo and CI

## v0.2 — Tactical RPG (implemented)

- encounter aggregate
- deterministic initiative order
- rounds/turn cursor
- action, bonus-action, reaction, and movement budgets
- typed resolution contexts/outcomes
- modifier pipeline with provenance
- trigger and reaction hooks
- saving throws
- concentration/resource pools
- damage resistance/immunity/vulnerability
- effect durations and expiry
- areas of effect and targeting contracts
- grid/graph spatial adapter interfaces
- tactical event replay coverage
- v0.1 compatibility outside encounters

## v0.3 — Adventure Engine (implemented)

- graph-based world maps and transitions
- exploration/search/discovery
- data-driven NPC templates
- inventory containers, loot, equip/unequip
- dialogue graph engine with checks/requirements
- quest state machines
- merchants and transactions
- travel commands/events

## v0.4 — Living World (planned; not yet implemented)

- calendar and scheduled world jobs
- weather state
- NPC schedules
- faction relationships/reputation
- settlement/economy primitives
- off-screen encounter resolution
- rumors and dynamic quest generation
- resource regeneration and ecology hooks

## v0.5 — Multiple Frontends (implemented out of sequence)

- interactive async CLI
- Rich/Textual TUI adapter
- browser reference client
- stable `/api/v1` REST/OpenAPI contract
- resumable WebSocket event subscriptions backed by persisted sequence cursors
- renderer-neutral observation/query API
- authenticated AsyncSSH terminal transport
- shared `serve-all` API + SSH authority process

v0.5 is presentation/transport work over existing campaign state and does not imply v0.4 is complete.

## v0.6 — Visual Adapters (implemented out of sequence)

- renderer-neutral `VisualSnapshot` contract derived from viewer-scoped observations
- data-driven asset/scene/event binding manifests
- resumable presentation-hint REST/WebSocket stream derived from persisted events
- movement interpolation hints
- animation/VFX/audio hints that remain non-authoritative
- Godot 4.7 2D reference adapter
- Godot 4.7 3D reference adapter
- scene/actor asset binding support
- SSH/terminal ASCII visual adapter using the same `VisualSnapshot`
- `map` / `visual` terminal commands
- shared visual bindings for API, Godot, local terminal, and SSH

v0.6 is also presentation work and can sit on top of v0.5 without the future living-world systems.
The next unimplemented simulation-depth milestone remains v0.4.

## v0.7 — AI Game Master

- observation filtering
- AI command-provider protocol
- utility AI / behavior tree reference agents
- narrator protocol
- NPC memory/context store
- procedural encounter/quest proposals requiring engine validation
- offline evaluation and deterministic scenario benchmarks

## v0.8 — Multiplayer

- authoritative hosted campaign service
- authenticated players/party membership
- optimistic client command IDs + idempotency
- reconnect/resume
- spectators
- rate limits and abuse controls
- horizontal campaign placement

## v0.9 — Creator Platform

- content-pack SDK and schema tooling
- campaign editor
- map graph editor
- creature/item/effect editors
- rules plugin SDK
- validation/lint tooling
- dependency/version constraints for mods

## v1.0 — RPG Platform

- stable engine/rules/content APIs
- hosted campaigns
- downloadable clients
- public engine API
- community content distribution
- optional creator marketplace

## Cross-cutting architecture milestones

### Deterministic event sourcing

Add command envelopes, command idempotency keys, rules/content version hashes, state hashes, replay,
rewind, branching timelines, and verification tools.

### Spatial authority

v0.2 establishes grid/graph adapter contracts. Later milestones deepen these with occupancy, collision,
pathfinding, line of sight, cover, terrain, and continuous-space semantics without renderer coupling.

### Intelligent living actors

Add perception, goals, utility scoring, behavior trees, tactical planning, schedules, and persistent
memories through the same command API used by humans.
