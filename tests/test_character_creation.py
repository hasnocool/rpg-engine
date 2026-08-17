"""v1.0.1 authoritative character-creation and replay tests."""

from copy import deepcopy

import pytest

from rpg_engine.character_creation import CharacterCreationError, CharacterCreationRuntime
from rpg_engine.commands import (
    AssignCharacterAbilitiesCommand,
    BeginCharacterCreationCommand,
    FinalizeCharacterCommand,
    GenerateCharacterAbilitiesCommand,
    UpdateCharacterDraftCommand,
)
from rpg_engine.content.models import ContentRegistry, WorldLocationSpec
from rpg_engine.dice import DeterministicRNG
from rpg_engine.events import CharacterAbilitiesGeneratedEvent
from rpg_engine.models import (
    Ability,
    AbilityGenerationMethod,
    CharacterDescription,
    WorldState,
)
from rpg_engine.reducer import apply_event


def runtime(seed: int = 1234) -> tuple[WorldState, CharacterCreationRuntime]:
    world = WorldState(campaign_id="campaign", seed=seed)
    content = ContentRegistry.with_core_defaults()
    content.locations["village"] = WorldLocationSpec(
        id="village",
        name="Village",
        region="north",
    )
    return world, CharacterCreationRuntime(
        world,
        content=content,
        rng=DeterministicRNG(seed, world.rng_counters),
    )


def begin_and_choose(rt: CharacterCreationRuntime) -> None:
    rt.execute(
        BeginCharacterCreationCommand(
            draft_id="hero-draft",
            entity_id="hero",
            name="Arin",
        )
    )
    rt.execute(
        UpdateCharacterDraftCommand(
            draft_id="hero-draft",
            ancestry_id="human",
            class_id="fighter",
            background_id="wanderer",
            description=CharacterDescription(
                pronouns="they/them",
                appearance="Travel-worn cloak and a calm expression.",
                backstory="A road-worn traveler seeking a place worth defending.",
            ),
        )
    )


def test_standard_array_finalizes_normal_entity_and_profile() -> None:
    world, rt = runtime()
    begin_and_choose(rt)
    generated = rt.execute(
        GenerateCharacterAbilitiesCommand(
            draft_id="hero-draft",
            method=AbilityGenerationMethod.STANDARD_ARRAY,
        )
    )
    assert isinstance(generated[0], CharacterAbilitiesGeneratedEvent)
    assert generated[0].score_pool == [15, 14, 13, 12, 10, 8]

    rt.execute(
        AssignCharacterAbilitiesCommand(
            draft_id="hero-draft",
            method=AbilityGenerationMethod.STANDARD_ARRAY,
            scores={
                Ability.STRENGTH: 15,
                Ability.DEXTERITY: 14,
                Ability.CONSTITUTION: 13,
                Ability.INTELLIGENCE: 12,
                Ability.WISDOM: 10,
                Ability.CHARISMA: 8,
            },
        )
    )
    events = rt.execute(
        FinalizeCharacterCommand(
            draft_id="hero-draft",
            start_location_id="village",
        )
    )

    assert [event.type for event in events] == ["entity_created", "character_finalized"]
    hero = world.entities["hero"]
    profile = world.characters["hero"]
    assert hero.stats.strength == 16
    assert hero.stats.dexterity == 15
    assert hero.stats.constitution == 14
    assert hero.stats.armor_class == 12
    assert hero.health is not None and hero.health.maximum == 12
    assert hero.position.area == "village"
    assert profile.ancestry_id == "human"
    assert profile.class_id == "fighter"
    assert profile.description.pronouns == "they/them"
    assert "player_character" in hero.identity.tags


def test_point_buy_rejects_scores_over_27_points() -> None:
    _, rt = runtime()
    begin_and_choose(rt)
    with pytest.raises(CharacterCreationError, match="exceeds budget"):
        rt.execute(
            AssignCharacterAbilitiesCommand(
                draft_id="hero-draft",
                method=AbilityGenerationMethod.POINT_BUY,
                scores={ability: 15 for ability in Ability},
            )
        )


def test_rolled_scores_are_deterministic_for_seed_and_draft() -> None:
    _, first = runtime(seed=9876)
    _, second = runtime(seed=9876)
    begin_and_choose(first)
    begin_and_choose(second)

    command = GenerateCharacterAbilitiesCommand(
        draft_id="hero-draft",
        method=AbilityGenerationMethod.ROLLED,
    )
    first_event = first.execute(command)[0]
    second_event = second.execute(command)[0]
    assert isinstance(first_event, CharacterAbilitiesGeneratedEvent)
    assert isinstance(second_event, CharacterAbilitiesGeneratedEvent)
    assert first_event.score_pool == second_event.score_pool
    assert first_event.rolls == second_event.rolls
    assert len(first_event.score_pool) == 6
    assert all(3 <= score <= 18 for score in first_event.score_pool)


def test_character_events_replay_draft_profile_and_entity() -> None:
    source, source_rt = runtime(seed=222)
    begin_and_choose(source_rt)
    raw_events = []
    raw_events.extend(
        source_rt.execute(
            GenerateCharacterAbilitiesCommand(
                draft_id="hero-draft",
                method=AbilityGenerationMethod.STANDARD_ARRAY,
            )
        )
    )
    raw_events.extend(
        source_rt.execute(
            AssignCharacterAbilitiesCommand(
                draft_id="hero-draft",
                method=AbilityGenerationMethod.STANDARD_ARRAY,
                scores={
                    Ability.STRENGTH: 15,
                    Ability.DEXTERITY: 14,
                    Ability.CONSTITUTION: 13,
                    Ability.INTELLIGENCE: 12,
                    Ability.WISDOM: 10,
                    Ability.CHARISMA: 8,
                },
            )
        )
    )
    raw_events.extend(source_rt.execute(FinalizeCharacterCommand(draft_id="hero-draft")))

    target = WorldState(campaign_id="campaign", seed=222)
    initial_draft = deepcopy(source.character_drafts["hero-draft"])
    initial_draft.finalized = False
    initial_draft.generated_method = None
    initial_draft.generated_ability_pool = []
    initial_draft.ability_generation_count = 0
    initial_draft.ability_method = None
    initial_draft.ability_scores = {}
    target.character_drafts["hero-draft"] = initial_draft

    sequence = 0
    for raw in raw_events:
        sequence += 1
        event = raw.model_copy(
            update={
                "sequence": sequence,
                "campaign_id": target.campaign_id,
                "rng_counters_after": dict(source.rng_counters),
            }
        )
        apply_event(target, event)  # type: ignore[arg-type]

    assert target.entities["hero"] == source.entities["hero"]
    assert target.characters["hero"] == source.characters["hero"]
    assert target.character_drafts["hero-draft"].finalized is True
