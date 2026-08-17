"""v0.7 AI Game Master observation, agent, memory, proposal, and evaluation tests."""

from __future__ import annotations

import asyncio

import pytest

from rpg_engine.ai_agents import BehaviorTreeAgent, DeterministicNarrator, UtilityAgent
from rpg_engine.ai_coordinator import AIGameMasterCoordinator
from rpg_engine.ai_eval import BenchmarkScenario, evaluate_provider
from rpg_engine.ai_memory import NpcMemoryContextStore
from rpg_engine.ai_observations import build_ai_observation
from rpg_engine.ai_protocols import NarrationRequest
from rpg_engine.ai_runtime import AIGameMasterRuntime
from rpg_engine.commands import (
    ActivateAiProposalCommand,
    AttackTargetCommand,
    RecordNpcMemoryCommand,
    SubmitAiEncounterProposalCommand,
    SubmitAiQuestProposalCommand,
)
from rpg_engine.content.models import (
    ContentRegistry,
    DynamicQuestTemplateSpec,
    WorldConnectionSpec,
    WorldLocationSpec,
)
from rpg_engine.events import AiProposalEvaluatedEvent, NpcMemoryRecordedEvent
from rpg_engine.models import (
    ActionBudget,
    AdventureKnowledge,
    AiEncounterProposal,
    AiQuestProposal,
    EncounterState,
    Entity,
    Health,
    Identity,
    InitiativeEntry,
    NpcMemory,
    Position,
    WorldState,
)
from rpg_engine.reducer import apply_event


def actor(entity_id: str, *, area: str = "village", hp: int = 10) -> Entity:
    return Entity(
        id=entity_id,
        identity=Identity(name=entity_id),
        health=Health(current=hp, maximum=10),
        position=Position(region="vale", area=area),
    )


def content() -> ContentRegistry:
    registry = ContentRegistry.with_core_defaults()
    registry.locations = {
        "village": WorldLocationSpec(id="village", name="Village", region="vale"),
        "forest": WorldLocationSpec(id="forest", name="Forest", region="vale"),
        "ruins": WorldLocationSpec(id="ruins", name="Ruins", region="vale"),
    }
    registry.connections = {
        "road": WorldConnectionSpec(
            id="road",
            from_location_id="village",
            to_location_id="forest",
            travel_minutes=20,
        ),
        "secret": WorldConnectionSpec(
            id="secret",
            from_location_id="village",
            to_location_id="ruins",
            travel_minutes=5,
            hidden=True,
        ),
    }
    registry.dynamic_quest_templates = {
        "patrol": DynamicQuestTemplateSpec(
            id="patrol",
            title="Patrol",
            description="Check the road.",
            target_location_ids=["forest"],
        )
    }
    return registry


def combat_world() -> WorldState:
    world = WorldState(campaign_id="ai", seed=7)
    world.entities = {
        "npc": actor("npc"),
        "enemy": actor("enemy", hp=3),
        "remote": actor("remote", area="forest"),
    }
    world.entity_templates["npc"] = "guard"
    world.encounters["fight"] = EncounterState(
        id="fight",
        participant_ids=["npc", "enemy"],
        initiative=[
            InitiativeEntry(actor_id="npc", die_roll=15, modifier=0, total=15),
            InitiativeEntry(actor_id="enemy", die_roll=10, modifier=0, total=10),
        ],
        budgets={"npc": ActionBudget(), "enemy": ActionBudget()},
    )
    return world


def test_ai_observation_filters_hidden_and_remote_state_and_includes_ranked_memory() -> None:
    world = combat_world()
    world.knowledge["npc"] = AdventureKnowledge(location_ids={"village"})
    world.npc_memories["npc"] = {
        "old": NpcMemory(
            id="old",
            actor_id="npc",
            summary="old detail",
            importance=20,
            tags={"road"},
            created_sequence=1,
            created_at_minute=0,
        ),
        "important": NpcMemory(
            id="important",
            actor_id="npc",
            summary="important detail",
            importance=90,
            tags={"enemy"},
            created_sequence=2,
            created_at_minute=0,
        ),
    }

    observation = build_ai_observation(
        world,
        content(),
        actor_id="npc",
        memory_limit=1,
        memory_tags={"enemy"},
    )

    assert [actor.id for actor in observation.nearby_actors] == ["enemy"]
    assert observation.location is not None
    assert [exit.connection_id for exit in observation.location.exits] == ["road"]
    assert [memory.id for memory in observation.memories] == ["important"]
    assert observation.nearby_actors[0].equipment == {}


def test_memory_store_filters_expired_and_scores_tags_subjects_importance() -> None:
    world = WorldState(campaign_id="memory", seed=1, time_minutes=50)
    world.npc_memories["npc"] = {
        "expired": NpcMemory(
            id="expired",
            actor_id="npc",
            summary="gone",
            importance=100,
            created_sequence=10,
            created_at_minute=0,
            expires_at_minute=40,
        ),
        "subject": NpcMemory(
            id="subject",
            actor_id="npc",
            summary="subject",
            importance=50,
            subject_ids={"hero"},
            created_sequence=3,
            created_at_minute=0,
        ),
        "tagged": NpcMemory(
            id="tagged",
            actor_id="npc",
            summary="tagged",
            importance=40,
            tags={"danger"},
            created_sequence=2,
            created_at_minute=0,
        ),
    }
    found = NpcMemoryContextStore(world).relevant(
        "npc", tags={"danger"}, subject_ids={"hero"}, limit=3
    )
    assert [memory.id for memory in found] == ["tagged", "subject"]


@pytest.mark.asyncio
async def test_utility_and_behavior_tree_agents_choose_deterministic_valid_actions() -> None:
    observation = build_ai_observation(combat_world(), content(), actor_id="npc")
    utility = await UtilityAgent().propose(observation)
    tree = await BehaviorTreeAgent().propose(observation)
    assert isinstance(utility.command, AttackTargetCommand)
    assert isinstance(tree.command, AttackTargetCommand)
    assert utility.command.target_id == "enemy"
    assert tree.command.target_id == "enemy"


@pytest.mark.asyncio
async def test_reference_narrator_is_descriptive_and_does_not_mutate_world() -> None:
    world = combat_world()
    before = world.model_copy(deep=True)
    observation = build_ai_observation(world, content(), actor_id="npc")
    result = await DeterministicNarrator().narrate(NarrationRequest(observation=observation))
    assert result.authoritative is False
    assert "npc" in result.text
    assert world == before


def test_memory_and_proposal_runtime_validate_before_follow_up_commands() -> None:
    world = combat_world()
    registry = content()
    runtime = AIGameMasterRuntime(world, content=registry)

    memory_result = runtime.execute(
        RecordNpcMemoryCommand(
            actor_id="npc",
            memory_id="m1",
            summary="Enemy was seen near the village.",
            tags={"enemy"},
        )
    )
    assert isinstance(memory_result.events[0], NpcMemoryRecordedEvent)

    encounter = runtime.execute(
        SubmitAiEncounterProposalCommand(
            proposal=AiEncounterProposal(
                id="ambush",
                participant_ids=["npc", "enemy"],
                location_id="village",
            ),
            activate=True,
        )
    )
    evaluated = encounter.events[0]
    assert isinstance(evaluated, AiProposalEvaluatedEvent)
    assert evaluated.record.status == "rejected"
    assert encounter.follow_up is None

    world.encounters.clear()
    encounter = runtime.execute(
        SubmitAiEncounterProposalCommand(
            proposal=AiEncounterProposal(
                id="ambush-2",
                participant_ids=["npc", "enemy"],
                location_id="village",
            ),
            activate=True,
        )
    )
    assert encounter.events[0].record.status == "validated"
    assert encounter.follow_up is not None
    assert encounter.follow_up.type == "start_encounter"

    quest = runtime.execute(
        SubmitAiQuestProposalCommand(
            proposal=AiQuestProposal(
                id="quest-1",
                origin_location_id="village",
                template_id="patrol",
                actor_id="npc",
            ),
            activate=True,
        )
    )
    assert quest.events[0].record.status == "validated"
    assert quest.follow_up is not None
    assert quest.follow_up.type == "generate_dynamic_quest"

    activation = runtime.execute(ActivateAiProposalCommand(proposal_id="quest-1"))
    assert activation.follow_up is not None
    assert activation.follow_up.type == "generate_dynamic_quest"
    activated_event = runtime.mark_activated("quest-1")
    assert activated_event.record.status == "activated"


def test_ai_memory_and_proposal_events_replay_exactly() -> None:
    base = WorldState(campaign_id="replay-ai", seed=3)
    base.entities["npc"] = actor("npc")
    world = base.model_copy(deep=True)
    runtime = AIGameMasterRuntime(world, content=content())
    raw_events = []
    raw_events += list(
        runtime.execute(
            RecordNpcMemoryCommand(
                actor_id="npc",
                memory_id="m1",
                summary="Remember this.",
            )
        ).events
    )
    raw_events += list(
        runtime.execute(
            SubmitAiQuestProposalCommand(
                proposal=AiQuestProposal(
                    id="quest",
                    origin_location_id="village",
                    template_id="patrol",
                )
            )
        ).events
    )

    replayed = base.model_copy(deep=True)
    for sequence, raw in enumerate(raw_events, start=1):
        event = raw.model_copy(
            update={
                "sequence": sequence,
                "campaign_id": replayed.campaign_id,
                "rng_counters_after": {},
            }
        )
        apply_event(replayed, event)
    assert replayed.npc_memories == world.npc_memories
    assert replayed.ai_proposals == world.ai_proposals


@pytest.mark.asyncio
async def test_async_coordinator_serializes_same_actor_without_blocking_event_loop() -> None:
    world = WorldState(campaign_id="coord", seed=1)
    world.entities["npc"] = actor("npc")
    registry = content()
    active = 0
    max_active = 0

    async def state_loader(campaign_id: str) -> WorldState:
        assert campaign_id == "coord"
        await asyncio.sleep(0)
        return world.model_copy(deep=True)

    async def executor(campaign_id: str, command: object):
        nonlocal active, max_active
        assert campaign_id == "coord"
        assert command.type == "explore_location"
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return []

    coordinator = AIGameMasterCoordinator(provider_timeout_seconds=1)
    await asyncio.gather(
        coordinator.run_turn(
            campaign_id="coord",
            actor_id="npc",
            content=registry,
            provider=UtilityAgent(),
            state_loader=state_loader,
            command_executor=executor,
        ),
        coordinator.run_turn(
            campaign_id="coord",
            actor_id="npc",
            content=registry,
            provider=UtilityAgent(),
            state_loader=state_loader,
            command_executor=executor,
        ),
    )
    assert max_active == 1


@pytest.mark.asyncio
async def test_offline_benchmark_reports_repeatable_reference_agent() -> None:
    world = WorldState(campaign_id="bench", seed=5)
    world.entities["npc"] = actor("npc")
    scenario = BenchmarkScenario(
        id="explore",
        world=world,
        content=content(),
        actor_id="npc",
        expected_command_types=frozenset({"explore_location"}),
        repeats=3,
    )
    result = await evaluate_provider(UtilityAgent(), [scenario])
    assert result.total == 1
    assert result.passed == 1
    assert result.deterministic is True
    assert result.score == 1.0
