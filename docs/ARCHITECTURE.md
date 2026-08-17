# Architecture

## Authority boundary

`SimulationEngine` is the only object allowed to turn a command into authoritative state mutation.
Transport adapters, renderers, AI agents, and narrators remain outside that boundary.

```text
human / AI / bot / renderer
          |
       Command
          v
+-------------------------+
| CampaignService         |  async lock per campaign
| +---------------------+ |
| | SimulationEngine    | |
| | rules + RNG + state | |
| +----------+----------+ |
+------------|------------+
             | Events
             +--------------------+
             |                    |
         SQLite store       WebSocket clients
```

## Determinism

The engine uses a counter-based hash RNG. Each roll is addressed by:

```text
campaign seed + named stream + stream counter
```

Named streams prevent unrelated systems from consuming one global random sequence. RNG counters
are embedded in `WorldState`, therefore snapshot restore preserves future rolls exactly.

A future deterministic event-sourcing milestone will additionally record command envelopes,
ruleset/content hashes, and state hashes so replay can verify the entire simulation byte-for-byte.

## Commands and events

Commands are intent and may be rejected. Events are accepted facts and must contain enough
information for clients to present the result without re-running game rules.

Example:

```text
AttackTargetCommand
  -> validate entities/weapon/rules
  -> deterministic attack roll
  -> AttackRolledEvent
  -> optional damage roll
  -> DamageAppliedEvent
  -> optional ActorDefeatedEvent
```

The engine does not emit prose such as "Aric swings his sword." A narrator client can transform
these events into prose, animation, sound, or telemetry.

## Rules runtime

`RulesRuntime` is a narrow strategy interface. The engine asks it for mechanical values such as:

- ability/check modifier
- attack modifier
- damage modifier
- armor class

The next expansion should introduce typed resolution contexts/outcomes, modifiers, triggers,
reactions, and capabilities rather than adding system-specific branches to `SimulationEngine`.

## Content packs

`content/core` contains only original generic examples. YAML is validated into typed Pydantic
models before the engine sees it. Content loaders run in a worker thread when invoked from an
async server so filesystem reads do not block the event loop.

Planned pack layering:

```text
engine
  -> ruleset plugin
      -> content pack(s)
          -> campaign overrides
              -> save state
```

## Persistence

SQLite uses WAL mode and async access via `aiosqlite`.

```text
campaigns
  campaign_id, seed

events
  campaign_id, sequence, event_type, payload

snapshots
  campaign_id, sequence, world payload
```

Load path:

```text
latest snapshot + subsequent events -> current world
```

The service serializes mutations with one `asyncio.Lock` per campaign. Different campaigns can
execute concurrently while commands for one campaign stay ordered.

## Spatial model

`Position` is intentionally hybrid and renderer-neutral. Logical fields (`world`, `region`, `area`,
`scene`, `zone`) can support interactive fiction or graph travel while optional `x/y/z` coordinates
allow grid/2D/3D adapters. Geometry, collision, line of sight, occupancy, and pathfinding belong in
future spatial-authority adapters.

## AI boundary

AI should receive a filtered observation and return the exact same commands as a human client.
An LLM narrator may describe emitted events but cannot mutate `WorldState`. This keeps hallucinated
narrative from becoming game truth.
