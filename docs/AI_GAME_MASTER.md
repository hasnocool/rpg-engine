# AI Game Master — v0.7

v0.7 adds an advisory AI layer without weakening the engine's authoritative command/event boundary.
AI providers see filtered observations, propose typed commands, and receive the same validation as
human or remote clients. Narration is explicitly non-authoritative.

## Observation filtering

`build_ai_observation()` produces an actor-centric `AiObservation` rather than exposing raw
`WorldState`.

The filter includes only information the actor can legitimately use:

- the actor's own health, equipment, conditions, resources, and faction reputation
- actors in the same logical location
- hidden exits only after the actor has discovered them
- the actor's tactical encounter and action budget
- the actor's quests plus active dynamic quests tied to known locations
- local weather, settlement summary, and unexpired local rumors
- a bounded set of relevant NPC memories

Other actors' inventories/resources, remote actors, undiscovered connections, and unrelated global
state stay out of the observation.

## Command-provider protocol

`AICommandProvider` is asynchronous:

```python
class AICommandProvider(Protocol):
    name: str

    async def propose(self, observation: AiObservation) -> AICommandDecision: ...
```

A decision may contain one ordinary engine `Command` or no action. The provider never receives a
mutable engine reference and cannot mutate world state directly.

`AIGameMasterCoordinator` serializes decisions per `(campaign_id, actor_id)` using `asyncio.Lock`,
uses `asyncio.timeout` for provider/narrator calls, and delegates actual execution to an async
command executor such as `CampaignService.execute`. It performs no blocking sleeps or synchronous
network/file operations.

## Reference agents

v0.7 includes two deterministic baselines:

- `UtilityAgent` scores available tactical/exploration actions and resolves ties deterministically.
- `BehaviorTreeAgent` implements async selector/sequence/condition/decision nodes and ships with a
  simple combat-first, exploration-second reference tree.

These are useful fallbacks and benchmark baselines even when a model-backed provider is installed.

## Narrator protocol

`Narrator` is also asynchronous and returns `NarrationResult(authoritative=False)`. The reference
`DeterministicNarrator` only describes facts already present in the filtered observation/events.
Narrator prose is never reduced into `WorldState`.

## NPC memory/context

NPC memories are persisted in `WorldState.npc_memories` and event sourced with:

- `record_npc_memory`
- `forget_npc_memory`
- `NpcMemoryRecordedEvent`
- `NpcMemoryForgottenEvent`

A memory stores a bounded summary, importance, tags, subjects, creation sequence/time, and optional
expiry. `NpcMemoryContextStore` retrieves context deterministically using tag/subject relevance,
importance, recency, and memory ID as a stable final tie-breaker.

## Procedural proposals

AI-generated encounters and quests use a two-stage authority boundary.

### Encounter proposals

`submit_ai_encounter_proposal` validates:

- unique participants
- known and living entities
- no participant already in active tactical combat
- a known logical location
- participant co-location
- non-colliding generated encounter ID

Only a validated proposal can be activated. Activation delegates to the existing
`StartEncounterCommand`, so initiative/action-economy validation is still owned by the tactical
engine.

### Quest proposals

`submit_ai_quest_proposal` intentionally cannot inject arbitrary executable quest definitions. It
must reference an existing validated `DynamicQuestTemplateSpec` plus a valid origin location.
Activation delegates to the existing `GenerateDynamicQuestCommand`.

Proposal validation and activation are both immutable events and replay into `WorldState.ai_proposals`.

## Offline evaluation

`ai_eval.py` provides deterministic provider benchmarking without requiring a server or network:

- clone scenario state per run
- build the same filtered observation
- execute the provider multiple times
- fingerprint the typed command payload
- verify repeatability
- check the result against expected command types

`BenchmarkSuiteResult` reports per-case determinism, pass/fail, aggregate score, and provider name.
This is intended as the base for future regression suites comparing local models, hosted models,
behavior trees, and utility policies on the same scenarios.

## Safety and authority invariants

1. AI sees filtered observations, not arbitrary mutable state.
2. AI returns commands/proposals; it never writes `WorldState` directly.
3. Standard engine validation remains authoritative.
4. Arbitrary generated quest code/content is not accepted at runtime.
5. Narration is non-authoritative.
6. NPC memory is contextual state, not a mechanism for asserting new world facts.
7. Provider orchestration is async and serialized per actor.
8. Reference agents and benchmarks are deterministic and do not use process-global randomness.
