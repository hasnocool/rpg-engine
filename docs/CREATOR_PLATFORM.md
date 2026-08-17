# v0.9 Creator Platform

v0.9 adds an authoring SDK around the engine's existing data-driven content contracts. It does not
make editor state authoritative simulation state and it does not require the still-planned v0.8
multiplayer service.

## Goals

The Creator Platform provides one source of truth for:

- content-pack scaffolding;
- campaign blueprints;
- graph-based map authoring;
- creature/NPC authoring;
- item/weapon and effect authoring;
- every v0.3/v0.4 content category;
- JSON Schema generation;
- whole-pack linting and cross-reference validation;
- content-pack dependency/version constraints;
- rules-plugin discovery and compatibility checks;
- a local browser editor and a scriptable CLI/API.

The runtime content loader remains the final authority for content which enters a campaign.

## Workspace layout

A creator workspace is still an ordinary content pack:

```text
my_pack/
├── manifest.yaml             # runtime content identity
├── mod.yaml                  # optional v0.9 dependency/plugin metadata
├── campaigns/                # creator campaign blueprints
├── world/
│   ├── locations/
│   ├── connections/
│   └── discoveries/
├── npcs/                     # creature/NPC templates
├── items/
├── effects/
├── dialogue/
├── quests/
├── merchants/
├── containers/
├── weather/
├── schedules/
├── factions/
├── settlements/
├── dynamic_quests/
├── rumors/
├── ecology/
└── .creator/
    └── map-layout.yaml       # editor-only node coordinates
```

`campaigns/` and `.creator/` are authoring metadata. The normal simulation loader ignores them.
Logical map topology still comes exclusively from `world/locations` and `world/connections`.

## Start a pack

```bash
rpg-engine creator init ./my_pack \
  --id my_pack \
  --name "My Pack" \
  --version 0.1.0
```

The command refuses to overwrite a non-empty directory unless `--force` is supplied.

Create common resources:

```bash
rpg-engine creator new ./my_pack location village --name "River Village"
rpg-engine creator new ./my_pack location forest --name "North Forest"
rpg-engine creator new ./my_pack creature goblin --name "Goblin"
rpg-engine creator new ./my_pack item iron_sword --name "Iron Sword"
rpg-engine creator new ./my_pack effect burning --name "Burning"
rpg-engine creator new ./my_pack campaign first_campaign --name "First Campaign"
```

Connect map nodes:

```bash
rpg-engine creator connect ./my_pack village_forest \
  --from village \
  --to forest \
  --minutes 30
```

## Browser editor

Run the local creator service:

```bash
rpg-engine creator serve ./my_pack --host 127.0.0.1 --port 8010
```

Open `/creator` in a browser.

The bundled editor supports:

- category/resource browsing;
- schema-validated create/update/delete;
- starter templates;
- campaign blueprints;
- creature/NPC documents;
- item/weapon documents;
- effect documents;
- every other registered content category;
- pack validation reports;
- a graph map view with draggable editor-only node positions.

All filesystem work performed by FastAPI endpoints runs through `asyncio.to_thread`. The server does
not perform blocking file reads or writes on its event loop.

The default bind host is loopback. This editor writes files in its configured workspace and should
not be exposed to an untrusted network without an authentication/reverse-proxy layer.

## Creator API

The local editor API is versioned independently of campaign simulation endpoints:

```text
GET    /api/creator/v1/info
GET    /api/creator/v1/schemas
GET    /api/creator/v1/resources?kind=item
GET    /api/creator/v1/resources/{kind}/{id}
PUT    /api/creator/v1/resources/{kind}/{id}
POST   /api/creator/v1/resources/{kind}/{id}/template
DELETE /api/creator/v1/resources/{kind}/{id}
GET    /api/creator/v1/map
PUT    /api/creator/v1/map/layout
POST   /api/creator/v1/validate
GET    /api/creator/v1/dependencies
```

Resource IDs are constrained before paths are constructed, and updates use same-directory temporary
files followed by `os.replace`, preventing partial YAML writes.

## JSON Schema

Generate all creator schemas:

```bash
rpg-engine creator schema --output ./schemas
```

Or one category:

```bash
rpg-engine creator schema --kind creature --output ./schemas
```

The bundle contains schemas for runtime resources plus:

- `manifest.yaml`;
- `mod.yaml`;
- rules-plugin descriptors;
- campaign blueprints.

The same Pydantic models used by the editor produce these schemas, avoiding a second hand-maintained
schema definition.

## Content/mod dependencies

Existing `manifest.yaml` remains backward compatible:

```yaml
id: northern_expansion
name: Northern Expansion
version: 1.2.0
ruleset: d20
```

v0.9 adds optional `mod.yaml` metadata:

```yaml
schema_version: 1
engine: ">=0.9,<1.0"
dependencies:
  - id: base_world
    version: ">=2.0,<3.0"
  - id: optional_cosmetics
    version: ">=1.0"
    optional: true
rules_plugins:
  - id: d20
    version: ">=0.9,<1.0"
```

Constraints use PEP 440 syntax. `*` means any version.

Resolve a pack with explicit available dependencies:

```bash
rpg-engine creator deps ./northern_expansion \
  --available ../base_world \
  --available ../optional_cosmetics \
  --discover-plugins
```

Resolution is deterministic and rejects:

- duplicate pack IDs;
- invalid versions/specifiers;
- missing required packs;
- incompatible dependency versions;
- incompatible engine versions;
- dependency cycles;
- missing/incompatible required rules plugins.

Optional dependencies may be absent. If present, they must still satisfy their declared constraint.

## Lint and validation

```bash
rpg-engine creator validate ./my_pack
```

The validator checks individual schemas first, then the engine's existing whole-pack
cross-reference validator. Additional creator diagnostics include:

- resource ID / filename mismatches;
- malformed YAML resources;
- campaign references to unknown locations/creature templates;
- disconnected map graph components;
- unreachable dialogue nodes;
- non-terminal quest states with no outgoing transition;
- dependency, engine, and rules-plugin constraints;
- informational authoring quality hints such as blank location descriptions.

A validation error exits the CLI with status 1 for CI use.

## Rules plugin SDK

Rules plugins publish a Python entry point in the stable group:

```toml
[project.entry-points."rpg_engine.rules_plugins"]
example = "example_rules:plugin"
```

The object exposes a descriptor and creates an existing `RulesRuntime`:

```python
class ExampleRulesPlugin:
    descriptor = RulesPluginDescriptor(
        id="example_rules",
        name="Example Rules",
        version="0.1.0",
        engine=">=0.9,<1.0",
    )

    def create_runtime(self) -> RulesRuntime:
        return ExampleRulesRuntime()
```

`RulesPluginRegistry` validates:

- unique plugin IDs;
- plugin versions;
- creator/rules API version;
- engine compatibility;
- returned `RulesRuntime` type;
- content-pack plugin requirements.

Entry-point discovery can import package metadata and code from disk, so asynchronous discovery is
provided through `discover_rules_plugins_async()`, which delegates the blocking discovery work to a
worker thread.

See `examples/rules_plugin/` for a minimal installable plugin.

## Authority boundary

Creator documents are proposals for content, not campaign facts:

```text
Creator UI / CLI
      |
      v
validated YAML + JSON Schema
      |
      v
normal ContentRegistry loader
      |
      v
SimulationEngine
```

The editor does not mutate `WorldState`, replay logs, RNG counters, encounter state, or live campaign
saves. This keeps authoring tools separate from deterministic simulation authority.

## Roadmap sequencing

v0.9 is implemented directly on the green v0.7 AI Game Master branch because creator tooling does
not require multiplayer. v0.8 remains planned and is not claimed as implemented by this milestone.
The separate v0.5/v0.6 presentation branches can consume v0.9-authored content after the branch
lines are converged.
