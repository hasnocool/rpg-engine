# rpg-engine

A **headless, deterministic, event-driven RPG simulation engine** for Python 3.12+.

The authoritative simulation is presentation-agnostic. Humans, AI agents, APIs, terminal clients,
visual clients, and future multiplayer hosts issue the same typed commands and consume immutable
events.

> The built-in `d20` runtime and `content/core` pack are original generic examples. Proprietary
> tabletop rulebooks or campaign content are not bundled.

## Current milestone: v0.9.0 Creator Platform

v0.9 adds a schema-driven authoring layer on top of the green v0.7 AI Game Master branch:

- content-pack SDK and canonical creator resource catalog
- generated JSON Schema for content and plugin tooling
- campaign blueprint editor
- graph map editor
- creature/NPC editor
- item/weapon and effect editors
- generic editing for the existing adventure/living-world content types
- browser, REST, and CLI creator workflows
- whole-pack linting and cross-reference diagnostics
- mod dependency/version/engine constraints
- rules-plugin SDK and entry-point discovery
- plugin API/version/engine compatibility checks
- atomic file replacement and async-safe creator API filesystem operations

v0.8 Multiplayer remains planned. v0.9 is intentionally implementable without it because authoring
content does not require player sessions, party authentication, or horizontal campaign placement.

## Architecture

```text
                       AUTHORING SIDE

 Creator CLI       Browser editor       External schema tooling
      |                  |                       |
      +----------- Creator Platform SDK --------+
                         |
              validated YAML / mod metadata
                         |
                         v
                  ContentRegistry loader
                         |
                         v
                       ENGINE
                         |
Human / AI ---------> Command
                         |
                         v
+--------------------------------------------------+
| CampaignService                                  |
| +----------------------------------------------+ |
| | SimulationEngine                             | |
| | + Tactical engine                            | |
| | + AdventureRuntime                           | |
| | + TimelineScheduler                          | |
| | + LivingWorldRuntime                         | |
| | + AIGameMasterRuntime                        | |
| | + RulesRuntime / hooks / deterministic RNG   | |
| +----------------------+-----------------------+ |
+------------------------|-------------------------+
                         | immutable Events
                         v
                  SQLite / replay / clients
```

Creator state is never authoritative campaign state. Editing a map node, quest, creature, or effect
changes files in a content workspace; it does not mutate a running `WorldState` or event log.

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Run the engine

```bash
rpg-engine demo --seed 918392482
rpg-engine serve --host 127.0.0.1 --port 8000
```

## Start a creator workspace

```bash
rpg-engine creator init ./my_campaign \
  --id my_campaign \
  --name "My Campaign" \
  --version 0.1.0
```

Create content from valid starter templates:

```bash
rpg-engine creator new ./my_campaign location village --name "Village"
rpg-engine creator new ./my_campaign location forest --name "Forest"
rpg-engine creator connect ./my_campaign village_forest \
  --from village --to forest --minutes 30

rpg-engine creator new ./my_campaign creature goblin --name "Goblin"
rpg-engine creator new ./my_campaign item iron_sword --name "Iron Sword"
rpg-engine creator new ./my_campaign effect burning --name "Burning"
rpg-engine creator new ./my_campaign campaign first_run --name "First Run"
```

Validate it:

```bash
rpg-engine creator validate ./my_campaign
```

A pack with validation errors exits with status 1, so the same command can run in CI.

## Browser creator

```bash
rpg-engine creator serve ./my_campaign --host 127.0.0.1 --port 8010
```

Open `/creator` in a browser. The built-in dependency-free editor provides:

- resource category browsing
- schema-validated JSON editing persisted as YAML
- resource scaffolding
- create/update/delete
- validation reports
- campaign, creature, item, and effect editing
- a graph map view
- draggable creator-only map layout coordinates

The browser service defaults to loopback. Filesystem operations are delegated through
`asyncio.to_thread`, keeping blocking reads/fsync/atomic file replacement off the FastAPI event loop.

See [`docs/CREATOR_PLATFORM.md`](docs/CREATOR_PLATFORM.md).

## JSON Schema tooling

Generate the full schema bundle:

```bash
rpg-engine creator schema --output ./schemas
```

Generate one resource type:

```bash
rpg-engine creator schema --kind creature --output ./schemas
```

The schema catalog comes from the same Pydantic models used to validate editor writes, rather than a
second manually maintained description of the content format.

## Mod dependency metadata

Runtime `manifest.yaml` remains small and backward compatible:

```yaml
id: northern_expansion
name: Northern Expansion
version: 1.2.0
ruleset: d20
```

v0.9 optionally adds `mod.yaml`:

```yaml
schema_version: 1
engine: ">=0.9,<1.0"
dependencies:
  - id: base_world
    version: ">=2.0,<3.0"
rules_plugins:
  - id: d20
    version: ">=0.9,<1.0"
```

Version requirements use PEP 440 constraints. Resolve available packs with:

```bash
rpg-engine creator deps ./northern_expansion \
  --available ../base_world \
  --discover-plugins
```

The resolver detects missing requirements, incompatible versions, engine incompatibility, duplicate
pack IDs, and dependency cycles. Optional dependencies may be absent but must be compatible when
present.

## Rules plugin SDK

Rules plugins publish under the entry-point group:

```toml
[project.entry-points."rpg_engine.rules_plugins"]
my_rules = "my_rules:plugin"
```

A plugin exposes a `RulesPluginDescriptor` and returns the existing `RulesRuntime` abstraction. The
registry validates plugin API version, plugin version, engine compatibility, duplicate IDs, runtime
type, and content-pack requirements.

```bash
rpg-engine creator plugins
```

See `examples/rules_plugin/` for a minimal plugin package.

## Creator validation

`creator validate` combines per-file schema checks with the engine's existing whole-pack validator.
It additionally reports authoring problems such as:

- resource filename/ID mismatches
- dependency/plugin incompatibility
- disconnected map locations
- unreachable dialogue nodes
- quest states which dead-end without being terminal
- campaign blueprints pointing at unknown locations or creature templates
- missing descriptive content hints

The authoritative content loader remains the final cross-reference gate before content reaches a
simulation.

## First-class time and Living World

The v0.4 branch provides one deterministic scheduler for:

```text
turn_based
timed_turn_based
real_time
real_time_with_pause
hybrid
```

The same queue handles actor readiness, delayed actions, spell completion, condition ticks, world
events, NPC schedules, reaction windows, weather/economy jobs, rumors, and ecology regeneration.
The scheduler never sleeps or polls wall time internally.

Living-world systems include deterministic regional weather, NPC schedules, factions/reputation,
settlement economy, off-screen encounter resolution, dynamic quests/rumors, and renewable resources.

See [`docs/LIVING_WORLD.md`](docs/LIVING_WORLD.md).

## AI Game Master

v0.7 keeps AI advisory rather than authoritative:

- filtered actor-centric observations
- asynchronous command providers
- deterministic utility/behavior-tree baselines
- non-authoritative narration
- event-sourced NPC memory
- engine-validated encounter/quest proposals
- deterministic offline evaluation

Providers return ordinary typed commands or proposals; existing engine rules decide what actually
happens.

See [`docs/AI_GAME_MASTER.md`](docs/AI_GAME_MASTER.md).

## Determinism and replay

Randomness uses named counter-based streams:

```text
campaign seed + stream name + stream counter -> deterministic roll
```

Logical time, scheduled jobs, RNG counters, tactical state, world outcomes, generated quests, AI
memory/proposals, and other authoritative mutations are represented by immutable events so snapshot
plus replay can reconstruct the simulation.

Creator files are deliberately outside that event stream: changing content is an authoring action,
not a hidden rewrite of campaign history.

## Test

```bash
ruff check .
pytest --cov=rpg_engine --cov-report=term-missing
```

## Roadmap sequencing

This v0.9 branch is stacked on v0.7 and deliberately skips the unfinished v0.8 multiplayer
milestone. The v0.5/v0.6 frontend/visual work exists on a separate parallel branch lineage. Those
branches can consume v0.9-authored packs after the project lines are converged.

See [`docs/ROADMAP.md`](docs/ROADMAP.md).
