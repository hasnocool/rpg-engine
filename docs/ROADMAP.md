# Roadmap

The project is intentionally staged so simulation depth is built before expensive presentation work.

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

- encounter aggregate and deterministic initiative
- rounds/turn cursor and action economy
- typed resolution/modifier provenance
- trigger/reaction hooks
- saving throws, concentration, resources, and damage traits
- effect durations and renderer-neutral spatial targeting
- tactical event replay

### v0.2.1 — First-class Time (integrated into v0.4)

- `turn_based`, `timed_turn_based`, `real_time`, `real_time_with_pause`, and `hybrid`
- one deterministic timeline for tactical and world scheduling
- bounded recurrence/backlog draining
- explicit monotonic wall-clock synchronization and pause semantics

## v0.3 — Adventure Engine (implemented)

- graph-based world maps and transitions
- exploration/search/discovery
- data-driven NPC templates
- inventory containers, loot, equip/unequip
- dialogue graph engine with checks/requirements
- quest state machines
- merchants and transactions
- travel commands/events

## v0.4 — Living World (implemented)

- calendar and scheduled world jobs
- deterministic regional weather
- NPC schedules and logical movement
- faction relationships and actor reputation
- settlement/economy primitives
- deterministic off-screen encounter resolution
- recurring rumors and dynamic quest generation/expiry
- resource harvesting, regeneration, and ecology hooks
- full event/reducer replay coverage for living-world state

## v0.5 — Multiple Frontends (parallel track)

- interactive CLI
- Rich/Textual TUI adapter
- browser reference client
- stable REST/OpenAPI contract
- resumable WebSocket event subscriptions
- renderer-neutral observation/query API

## v0.6 — Visual Adapters

- Godot 2D adapter
- Godot 3D adapter
- asset/scene binding manifests
- movement interpolation events
- animation/VFX/audio binding hints that remain non-authoritative

## v0.7 — AI Game Master (implemented)

- actor-centric observation filtering
- async AI command-provider protocol
- deterministic utility AI and behavior-tree reference agents
- async non-authoritative narrator protocol
- event-sourced NPC memory/context store
- procedural encounter/quest proposals requiring engine validation
- async per-actor coordination with provider timeouts
- offline evaluation and deterministic scenario benchmarks

## v0.8 — Multiplayer

- authoritative hosted campaign service
- authenticated players/party membership
- optimistic client command IDs + idempotency
- reconnect/resume and spectators
- rate limits and horizontal campaign placement

## v0.9 — Creator Platform

- content-pack SDK and schema tooling
- campaign/map/creature/item/effect editors
- rules plugin SDK
- validation/lint tooling
- dependency/version constraints for mods

## v1.0 — RPG Platform

- stable engine/rules/content APIs
- hosted campaigns and downloadable clients
- public engine API
- community content distribution
- optional creator marketplace

## Cross-cutting architecture milestones

### Deterministic event sourcing

Add command envelopes, idempotency keys, rules/content hashes, state hashes, replay verification,
rewind, and branching timelines.

### Spatial authority

Deepen the v0.2 grid/graph contracts with occupancy, collision, pathfinding, line of sight, cover,
terrain, and continuous-space semantics without renderer coupling.

### Intelligent living actors

Build perception, goals, utility scoring, behavior trees, tactical planning, and persistent memories
on top of v0.4 schedules and the same command API used by humans.
