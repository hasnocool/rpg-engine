# v1.0.1 Character Creator

v1.0.1 adds a D&D-style character-creation workflow without introducing a second character model.
The creator uses normal commands, immutable events, deterministic RNG, content packs, snapshots,
reducer replay, `/api/v1`, and the existing browser/client authority boundary.

## Workflow

1. `begin_character_creation` reserves a draft/entity ID and name.
2. `update_character_draft` records race/ancestry, class, background, and description.
3. Choose one ability method:
   - `standard_array`: 15, 14, 13, 12, 10, 8
   - `point_buy`: 27-point budget, scores 8–15
   - `rolled`: deterministic 4d6/drop-lowest for six scores
   - `manual`: six scores from 3–18
4. `assign_character_abilities` assigns all six abilities.
5. `finalize_character` validates the complete sheet and creates a normal `Entity`.

Generated dice use named deterministic streams, so campaign seed + draft + generation reproduce the
same rolls after replay. Standard-array and rolled assignments must use exactly the generated pool.
Point-buy is validated server-side.

## Final entity derivation

Finalization applies ancestry ability bonuses and derives level-1 engine state:

- HP = class hit die + Constitution modifier, minimum 1
- AC = 10 + Dexterity modifier
- movement speed = ancestry movement speed
- inventory/currency = merged class + background starting equipment
- resources = class resource pools
- identity tags = player character + ancestry/class/background tags
- optional starting location = existing world location

The detailed character sheet is stored as `CharacterProfile`, while the entity is immediately usable
by combat, adventure, living-world, AI, observation, persistence, and frontend systems.

## Data-driven choices

Content packs can add or replace choices in:

```text
characters/ancestries/*.yaml
characters/classes/*.yaml
characters/backgrounds/*.yaml
```

Cross-file validation verifies class/background starting items. The engine also has original generic
fallback choices so character creation works with `ContentRegistry.with_core_defaults()`.

## Description fields

Character profiles support pronouns, age, appearance, personality, ideals, bonds, flaws, backstory,
goals, and notes. Nearby renderer-neutral observations expose only the public identity summary:
ancestry, class, background, level, pronouns, and appearance.

## Browser UI

Run the server and open:

```text
/character-creator
```

The browser UI loads `/api/v1/character-creation/catalog` and sends the same typed commands as any
CLI, TUI, SSH, AI, or external web client. The browser never computes authoritative final stats.
