# Tactical Runtime — v0.2

## Encounter aggregate

An `EncounterState` owns participants, deterministic initiative entries, round number, turn cursor,
and per-actor action budgets. An actor may belong to at most one active encounter.

Initiative is resolved through the same typed modifier pipeline as checks, attacks, and saves. Ties
are stable because ordering uses total, then modifier, then actor ID.

## Action economy

Each participant has an `ActionBudget` with:

- action
- bonus action
- reaction
- movement

The active actor may spend action/bonus/movement. Reaction spending is permitted out of turn only
when a persisted reaction window offers that reaction to the actor. Budgets reset from
`RulesRuntime.base_action_budget()` when the actor's next turn starts.

## Resolution pipeline

`ResolutionContext` describes what is being resolved. `Modifier` records each contribution and its
provenance. `ModifierPipeline` deterministically sorts, stacks, and totals modifiers before creating
`ResolutionOutcome`.

Events include both the compatibility `modifier` total and the full modifier list so clients can
render explanations such as:

```text
Attack roll: 14
+3 ability
+2 proficiency
=19
```

without recalculating rules.

## Damage traits

`DamageProfile` stores resistance, immunity, and vulnerability type sets. Resolution order is:

1. immunity -> zero damage
2. resistance + vulnerability -> neutral
3. resistance -> half, rounded down
4. vulnerability -> double
5. otherwise unchanged

`DamageAppliedEvent` preserves raw amount, multiplier, final amount, and HP after application.

## Effects, resources, and concentration

Effect content may declare action cost, resource costs, duration, concentration, and targeting.
Resource availability is validated before any effect operation mutates state.

Timed effects become `ActiveEffect` records. Duration ticks and expiry are explicit events so replay
reconstructs remaining duration exactly. Concentration points at the active effect instance; starting
a replacement ends the previous concentration effect first.

## Trigger/reaction hooks

`HookRegistry` evaluates registered hooks in stable name order. Hooks may derive `TriggerContext`
objects from authoritative events and offer typed `ReactionOffer` objects. The engine stores these as
`ReactionWindow` state.

A client cannot manufacture a valid reaction by sending an arbitrary reaction ID: `UseReactionCommand`
must match an authoritative open offer and consumes the encounter's reaction budget.

## Spatial contracts

The simulation depends on `SpatialAdapter`, not renderer geometry. v0.2 includes:

- `GridSpatialAdapter` for coordinate distance/movement/area queries
- `GraphSpatialAdapter` for weighted logical-node traversal
- `TargetingContract` for single/radius/line/cone capability declarations

Line and cone shapes are contracts in v0.2; ruleset-specific geometry can refine their exact target
selection later without changing command/event or renderer boundaries.

## Replay

Tactical state is reconstructed from semantic events:

- encounter start/end
- turn start
- budget spend
- resource spend
- effect activation/tick/expiry
- concentration start/end
- trigger/reaction window events
- damage/healing/conditions/movement

The reducer also restores RNG counters from every event, preserving deterministic future rolls after
snapshot + replay recovery.
