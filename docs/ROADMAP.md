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

## v0.2.1 — First-class Time (implemented)

- one persisted deterministic timeline for tactical and world scheduling
- `turn_based`, `timed_turn_based`, `real_time`, `real_time_with_pause`, and `hybrid` modes
- explicit monotonic wall-clock synchronization with deterministic replay
- pause/resume semantics for pausable modes
- actor readiness and turn-quantum advancement
- delayed actions and spell-completion scheduling
- recurring condition ticks and world events
- NPC schedule, reaction-window, and idle-pressure item types
- deterministic priority/insertion ordering
- bounded catch-up with explicit backlog draining
- timeline commands/events/reducer coverage
- legacy `advance_time` compatibility

See [`TIME.md`](TIME.md) for the scheduler contract and examples.

## v0.3 — Adventure Engine (next)

- graph-based world maps and transitions
- exploration/search/discovery
- data-driven NPC templates
- inventory containers, loot, equip/unequip
- dialogue graph engine with checks/requirements
- quest state machines
- merchants and transactions
- travel commands/events

## v0.4 — Living World

- calendar and scheduled world jobs built on the v0.2.1 timeline
- weather state
- NPC schedules
- faction relationships/reputation
- settlement/economy primitives
- off-screen encounter resolution
- rumors and dynamic quest generation
- resource regeneration and ecology hooks

## v0.5 — Multiple Frontends

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
rewind, branching timelines, and verification tools. v0.2.1 already makes timeline mutations replayable
through typed scheduler events.

### Spatial authority

v0.2 establishes grid/graph adapter contracts. Later milestones deepen these with occupancy, collision,
pathfinding, line of sight, cover, terrain, and continuous-space semantics without renderer coupling.

### Intelligent living actors

Add perception, goals, utility scoring, behavior trees, tactical planning, schedules, and persistent
memories through the same command API used by humans. NPC schedules should use the first-class
v0.2.1 timeline rather than a separate clock.
