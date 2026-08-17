# Adventure Engine

v0.3 turns the deterministic tactical engine into a reusable adventure simulation without adding a
presentation dependency.

## World graph

Locations and connections live in validated content. `TravelCommand` never supplies a trusted travel
cost: the engine selects a traversable connection, advances authoritative time, moves the actor's
logical `Position.area`, and emits `TravelCompletedEvent`.

Hidden connections require actor knowledge. This makes secret doors, forgotten paths, unlocked
routes, and discovered fast-travel links representable without geometry.

## Exploration and discovery

`ExploreLocationCommand` records that an actor explored a location and reveals automatic (`dc: 0`)
discoveries. `SearchLocationCommand` resolves one deterministic d20 check through the existing rules
modifier pipeline and reveals all matching undiscovered content whose DC is met.

A discovery can reveal:

- logical locations
- graph connections
- containers

Knowledge is actor-specific and event-sourced.

## NPC templates

`NpcTemplateSpec` wraps an ordinary `Entity` template and can bind it to dialogue and merchant
profiles. `SpawnNpcCommand` clones the template into an authoritative entity ID and location.
Merchant stock/funds are materialized into the entity at spawn time, so subsequent transactions are
ordinary state mutation plus immutable events.

## Containers and equipment

Containers are persistent runtime objects created from content templates when they are revealed.
Looting validates discovery, location, lock state, item quantities, and currency transfer.

Equipment uses explicit slots while retaining the v0.1 `equipped_item_ids` list for compatibility.
Equipping into an occupied slot first emits an unequip event, then an equip event.

Adventure inventory operations are disabled during active encounters so they cannot bypass v0.2
action budgets.

## Dialogue graphs

A dialogue contains nodes and options. Sessions persist the actor, NPC, dialogue, current node, and
active state.

Options may have:

- a deterministic ability check
- success/failure destinations
- quest-state requirements
- quest actions
- an explicit end flag

Checks emit the standard `CheckRolledEvent`, including modifier provenance, so clients can explain
why a dialogue check succeeded without running the rules themselves.

## Quest state machines

A quest declares:

```text
states
initial state
terminal states
(from state, trigger) -> to state transitions
```

`StartQuestCommand` materializes progress. `AdvanceQuestCommand` validates the requested trigger
against the current state. Dialogue options call the same internal transition path, so quests behave
identically whether advanced by UI, scripted content, or a future AI agent.

## Merchants

Merchant profiles define stock, starting funds, currency, buy/sell multipliers, and optional item
price overrides.

Transactions validate:

- co-location
- stock quantity
- equipped-item restrictions
- buyer funds
- item metadata

`TransactionCompletedEvent` stores the historical unit price, total, quantity, and exact resulting
inventory/balance state. Replay therefore does not depend on current merchant configuration.

## Replay contract

The reducer reconstructs:

- NPC/template bindings
- actor knowledge
- travel/time changes
- containers and loot
- equipment
- dialogue sessions
- quest progress
- merchant transactions

Together with the v0.1/v0.2 reducers and RNG counters, snapshot + subsequent events reconstructs the
same authoritative world state and the same future random sequence.
