"""D&D-style, content-driven character creation using normal engine authority."""

from __future__ import annotations

from collections import Counter

from pydantic import Field

from rpg_engine.commands import (
    AssignCharacterAbilitiesCommand,
    BeginCharacterCreationCommand,
    Command,
    FinalizeCharacterCommand,
    GenerateCharacterAbilitiesCommand,
    UpdateCharacterDraftCommand,
)
from rpg_engine.content.models import (
    CharacterAncestrySpec,
    CharacterBackgroundSpec,
    CharacterClassSpec,
    ContentRegistry,
    WorldLocationSpec,
)
from rpg_engine.dice import DeterministicRNG
from rpg_engine.events import (
    CharacterAbilitiesGeneratedEvent,
    CharacterDraftCreatedEvent,
    CharacterDraftUpdatedEvent,
    CharacterFinalizedEvent,
    EntityCreatedEvent,
    EventBase,
)
from rpg_engine.models import (
    Ability,
    AbilityGenerationMethod,
    CharacterCreationDraft,
    CharacterProfile,
    Entity,
    Health,
    Identity,
    Inventory,
    Position,
    ResourcePool,
    Stats,
    StrictModel,
    WorldState,
)

STANDARD_ARRAY = [15, 14, 13, 12, 10, 8]
POINT_BUY_BUDGET = 27
POINT_BUY_COSTS = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}


class CharacterCreationError(ValueError):
    """Rejected character-creation intent."""


class CharacterCreationCatalog(StrictModel):
    """Resolved choices exposed to clients without granting state authority."""

    ancestries: list[CharacterAncestrySpec]
    classes: list[CharacterClassSpec]
    backgrounds: list[CharacterBackgroundSpec]
    locations: list[WorldLocationSpec] = Field(default_factory=list)
    ability_methods: list[AbilityGenerationMethod] = Field(
        default_factory=lambda: list(AbilityGenerationMethod)
    )
    standard_array: list[int] = Field(default_factory=lambda: list(STANDARD_ARRAY))
    point_buy_budget: int = POINT_BUY_BUDGET
    point_buy_costs: dict[int, int] = Field(default_factory=lambda: dict(POINT_BUY_COSTS))

    def ancestry_map(self) -> dict[str, CharacterAncestrySpec]:
        return {item.id: item for item in self.ancestries}

    def class_map(self) -> dict[str, CharacterClassSpec]:
        return {item.id: item for item in self.classes}

    def background_map(self) -> dict[str, CharacterBackgroundSpec]:
        return {item.id: item for item in self.backgrounds}


_DEFAULT_ANCESTRIES = {
    "human": CharacterAncestrySpec(
        id="human",
        name="Human",
        description="Adaptable people found across many cultures and regions.",
        ability_bonuses={ability: 1 for ability in Ability},
        movement_speed=30,
        tags={"human"},
    ),
    "wood_elf": CharacterAncestrySpec(
        id="wood_elf",
        name="Wood Elf",
        description="Graceful forest-dwellers with keen senses and practiced mobility.",
        ability_bonuses={Ability.DEXTERITY: 2, Ability.WISDOM: 1},
        movement_speed=35,
        tags={"elf"},
    ),
    "highland_dwarf": CharacterAncestrySpec(
        id="highland_dwarf",
        name="Highland Dwarf",
        description="Sturdy mountain folk known for endurance and practical strength.",
        ability_bonuses={Ability.CONSTITUTION: 2, Ability.STRENGTH: 1},
        movement_speed=25,
        tags={"dwarf"},
    ),
}

_DEFAULT_CLASSES = {
    "fighter": CharacterClassSpec(
        id="fighter",
        name="Fighter",
        description="A disciplined martial adventurer trained for direct conflict.",
        hit_die=10,
        primary_abilities={Ability.STRENGTH, Ability.DEXTERITY},
        saving_throw_abilities={Ability.STRENGTH, Ability.CONSTITUTION},
        starting_item_ids=["unarmed"],
        starting_currency={"gold": 10},
    ),
    "rogue": CharacterClassSpec(
        id="rogue",
        name="Rogue",
        description="A quick, precise adventurer who relies on mobility and cleverness.",
        hit_die=8,
        primary_abilities={Ability.DEXTERITY},
        saving_throw_abilities={Ability.DEXTERITY, Ability.INTELLIGENCE},
        starting_item_ids=["unarmed"],
        starting_currency={"gold": 12},
    ),
    "mage": CharacterClassSpec(
        id="mage",
        name="Mage",
        description="A student of supernatural forces who solves problems through knowledge.",
        hit_die=6,
        primary_abilities={Ability.INTELLIGENCE},
        saving_throw_abilities={Ability.INTELLIGENCE, Ability.WISDOM},
        starting_currency={"gold": 8},
        resource_pools={
            "focus": ResourcePool(current=2, maximum=2, recharge="long_rest")
        },
    ),
    "priest": CharacterClassSpec(
        id="priest",
        name="Priest",
        description="A devoted adventurer whose resolve and wisdom support the group.",
        hit_die=8,
        primary_abilities={Ability.WISDOM},
        saving_throw_abilities={Ability.WISDOM, Ability.CHARISMA},
        starting_currency={"gold": 10},
        resource_pools={
            "devotion": ResourcePool(current=2, maximum=2, recharge="long_rest")
        },
    ),
}

_DEFAULT_BACKGROUNDS = {
    "wanderer": CharacterBackgroundSpec(
        id="wanderer",
        name="Wanderer",
        description="You learned to travel light and adapt to unfamiliar places.",
        starting_currency={"gold": 5},
        tags={"traveler"},
    ),
    "artisan": CharacterBackgroundSpec(
        id="artisan",
        name="Artisan",
        description="You practiced a trade and learned the value of patient skilled work.",
        starting_currency={"gold": 15},
        tags={"craft"},
    ),
    "scholar": CharacterBackgroundSpec(
        id="scholar",
        name="Scholar",
        description="You spent years studying history, theory, languages, or natural philosophy.",
        starting_currency={"gold": 10},
        tags={"learned"},
    ),
}


def build_character_creation_catalog(content: ContentRegistry) -> CharacterCreationCatalog:
    """Merge built-in original examples with content-pack additions/overrides."""

    ancestries = {**_DEFAULT_ANCESTRIES, **content.character_ancestries}
    classes = {**_DEFAULT_CLASSES, **content.character_classes}
    backgrounds = {**_DEFAULT_BACKGROUNDS, **content.character_backgrounds}
    return CharacterCreationCatalog(
        ancestries=sorted(ancestries.values(), key=lambda item: item.id),
        classes=sorted(classes.values(), key=lambda item: item.id),
        backgrounds=sorted(backgrounds.values(), key=lambda item: item.id),
        locations=sorted(content.locations.values(), key=lambda item: item.id),
    )


def ability_modifier(score: int) -> int:
    return (score - 10) // 2


def point_buy_cost(scores: dict[Ability, int]) -> int:
    try:
        return sum(POINT_BUY_COSTS[value] for value in scores.values())
    except KeyError as exc:
        raise CharacterCreationError("point-buy scores must be between 8 and 15") from exc


class CharacterCreationRuntime:
    """Authoritative draft/finalize workflow for player characters."""

    _HANDLED = (
        BeginCharacterCreationCommand,
        UpdateCharacterDraftCommand,
        GenerateCharacterAbilitiesCommand,
        AssignCharacterAbilitiesCommand,
        FinalizeCharacterCommand,
    )

    def __init__(
        self,
        world: WorldState,
        *,
        content: ContentRegistry,
        rng: DeterministicRNG,
    ) -> None:
        self.world = world
        self.content = content
        self.rng = rng
        self.catalog = build_character_creation_catalog(content)

    @classmethod
    def handles(cls, command: Command) -> bool:
        return isinstance(command, cls._HANDLED)

    def _draft(self, draft_id: str) -> CharacterCreationDraft:
        draft = self.world.character_drafts.get(draft_id)
        if draft is None:
            raise CharacterCreationError(f"unknown character draft: {draft_id}")
        if draft.finalized:
            raise CharacterCreationError(f"character draft is already finalized: {draft_id}")
        return draft

    def _validate_choice(self, category: str, value: str | None) -> None:
        if value is None:
            return
        choices: dict[str, object]
        if category == "ancestry":
            choices = self.catalog.ancestry_map()
        elif category == "class":
            choices = self.catalog.class_map()
        else:
            choices = self.catalog.background_map()
        if value not in choices:
            raise CharacterCreationError(f"unknown {category}: {value}")

    def _validate_ability_scores(
        self,
        draft: CharacterCreationDraft,
        method: AbilityGenerationMethod,
        scores: dict[Ability, int],
    ) -> None:
        if set(scores) != set(Ability):
            missing = sorted(ability.value for ability in set(Ability) - set(scores))
            extra = sorted(str(ability) for ability in set(scores) - set(Ability))
            parts = [*(f"missing {item}" for item in missing), *(f"extra {item}" for item in extra)]
            details = ", ".join(parts)
            raise CharacterCreationError(f"all six ability scores are required: {details}")
        if method is AbilityGenerationMethod.POINT_BUY:
            cost = point_buy_cost(scores)
            if cost > POINT_BUY_BUDGET:
                raise CharacterCreationError(
                    f"point-buy cost {cost} exceeds budget {POINT_BUY_BUDGET}"
                )
            return
        if method is AbilityGenerationMethod.MANUAL:
            if any(not 3 <= score <= 18 for score in scores.values()):
                raise CharacterCreationError("manual base scores must be between 3 and 18")
            return
        if draft.generated_method is not method or not draft.generated_ability_pool:
            raise CharacterCreationError(f"generate {method.value} scores before assigning them")
        if Counter(scores.values()) != Counter(draft.generated_ability_pool):
            raise CharacterCreationError(
                "assigned ability scores must use exactly the generated score pool"
            )

    def _generate(
        self, draft: CharacterCreationDraft, method: AbilityGenerationMethod
    ) -> EventBase:
        if method is AbilityGenerationMethod.STANDARD_ARRAY:
            pool = list(STANDARD_ARRAY)
            rolls: list[list[int]] = []
        elif method is AbilityGenerationMethod.ROLLED:
            pool = []
            rolls = []
            attempt = draft.ability_generation_count + 1
            for index in range(6):
                result = self.rng.roll(
                    "4d6",
                    stream=f"character:{draft.id}:ability-roll:{attempt}:{index}",
                )
                raw = list(result.rolls)
                rolls.append(raw)
                pool.append(sum(sorted(raw)[1:]))
        else:
            raise CharacterCreationError(
                "generate_character_abilities supports standard_array or rolled"
            )
        draft.generated_method = method
        draft.generated_ability_pool = pool
        draft.ability_generation_count += 1
        draft.ability_scores = {}
        draft.ability_method = None
        return CharacterAbilitiesGeneratedEvent(
            draft_id=draft.id,
            method=method,
            score_pool=list(pool),
            rolls=rolls,
            generation=draft.ability_generation_count,
        )

    def _finalize(self, draft: CharacterCreationDraft, location_id: str | None) -> list[EventBase]:
        if draft.entity_id in self.world.entities:
            raise CharacterCreationError(f"entity already exists: {draft.entity_id}")
        if not draft.name.strip():
            raise CharacterCreationError("character name is required")
        if draft.ancestry_id is None or draft.class_id is None or draft.background_id is None:
            raise CharacterCreationError("ancestry, class, and background are required")
        if draft.ability_method is None or set(draft.ability_scores) != set(Ability):
            raise CharacterCreationError("complete all six ability scores before finalizing")

        ancestry = self.catalog.ancestry_map()[draft.ancestry_id]
        character_class = self.catalog.class_map()[draft.class_id]
        background = self.catalog.background_map()[draft.background_id]
        final_scores = {
            ability: draft.ability_scores[ability] + ancestry.ability_bonuses.get(ability, 0)
            for ability in Ability
        }
        if any(not 1 <= score <= 20 for score in final_scores.values()):
            raise CharacterCreationError("final level-1 ability scores must be between 1 and 20")

        if location_id is not None and location_id not in self.content.locations:
            raise CharacterCreationError(f"unknown starting location: {location_id}")
        location = self.content.locations.get(location_id) if location_id is not None else None
        position = Position(
            area=location_id,
            region=location.region if location is not None else None,
        )

        constitution = final_scores[Ability.CONSTITUTION]
        dexterity = final_scores[Ability.DEXTERITY]
        maximum_hp = max(1, character_class.hit_die + ability_modifier(constitution))
        item_ids = [*character_class.starting_item_ids, *background.starting_item_ids]
        missing_items = sorted(set(item_ids) - set(self.content.items))
        if missing_items:
            raise CharacterCreationError(
                f"character choices reference unknown starting items: {', '.join(missing_items)}"
            )
        currency: dict[str, int] = {}
        for source in (character_class.starting_currency, background.starting_currency):
            for currency_id, amount in source.items():
                currency[currency_id] = currency.get(currency_id, 0) + amount
        resources = {
            resource_id: pool.model_copy(deep=True)
            for resource_id, pool in character_class.resource_pools.items()
        }
        tags = {
            "player_character",
            f"ancestry:{ancestry.id}",
            f"class:{character_class.id}",
            f"background:{background.id}",
            *ancestry.tags,
            *background.tags,
        }
        entity = Entity(
            id=draft.entity_id,
            identity=Identity(name=draft.name.strip(), tags=tags),
            stats=Stats(
                **{ability.value: final_scores[ability] for ability in Ability},
                proficiency_bonus=2,
                armor_class=10 + ability_modifier(dexterity),
                movement_speed=ancestry.movement_speed,
            ),
            health=Health(current=maximum_hp, maximum=maximum_hp),
            position=position,
            inventory=Inventory(item_ids=item_ids, currency=currency),
            resources=resources,
        )
        profile = CharacterProfile(
            entity_id=entity.id,
            name=entity.identity.name,
            ancestry_id=ancestry.id,
            class_id=character_class.id,
            background_id=background.id,
            level=1,
            ability_method=draft.ability_method,
            base_ability_scores=dict(draft.ability_scores),
            final_ability_scores=final_scores,
            description=draft.description.model_copy(deep=True),
        )
        draft.finalized = True
        self.world.entities[entity.id] = entity.model_copy(deep=True)
        self.world.characters[entity.id] = profile.model_copy(deep=True)
        return [
            EntityCreatedEvent(entity=entity.model_copy(deep=True)),
            CharacterFinalizedEvent(
                draft_id=draft.id,
                draft=draft.model_copy(deep=True),
                profile=profile.model_copy(deep=True),
            ),
        ]

    def execute(self, command: Command) -> list[EventBase]:
        if isinstance(command, BeginCharacterCreationCommand):
            if command.draft_id in self.world.character_drafts:
                raise CharacterCreationError(f"character draft already exists: {command.draft_id}")
            if command.entity_id in self.world.entities:
                raise CharacterCreationError(f"entity already exists: {command.entity_id}")
            if any(
                draft.entity_id == command.entity_id
                for draft in self.world.character_drafts.values()
                if not draft.finalized
            ):
                raise CharacterCreationError(
                    f"another character draft already uses entity id: {command.entity_id}"
                )
            draft = CharacterCreationDraft(
                id=command.draft_id,
                entity_id=command.entity_id,
                name=command.name.strip(),
            )
            if not draft.name:
                raise CharacterCreationError("character name is required")
            self.world.character_drafts[draft.id] = draft
            return [CharacterDraftCreatedEvent(draft=draft.model_copy(deep=True))]

        if isinstance(command, UpdateCharacterDraftCommand):
            draft = self._draft(command.draft_id)
            self._validate_choice("ancestry", command.ancestry_id)
            self._validate_choice("class", command.class_id)
            self._validate_choice("background", command.background_id)
            if command.name is not None:
                name = command.name.strip()
                if not name:
                    raise CharacterCreationError("character name cannot be empty")
                draft.name = name
            if command.ancestry_id is not None:
                draft.ancestry_id = command.ancestry_id
            if command.class_id is not None:
                draft.class_id = command.class_id
            if command.background_id is not None:
                draft.background_id = command.background_id
            if command.description is not None:
                draft.description = command.description.model_copy(deep=True)
            return [CharacterDraftUpdatedEvent(draft=draft.model_copy(deep=True))]

        if isinstance(command, GenerateCharacterAbilitiesCommand):
            draft = self._draft(command.draft_id)
            return [self._generate(draft, command.method)]

        if isinstance(command, AssignCharacterAbilitiesCommand):
            draft = self._draft(command.draft_id)
            scores = dict(command.scores)
            self._validate_ability_scores(draft, command.method, scores)
            draft.ability_method = command.method
            draft.ability_scores = scores
            return [CharacterDraftUpdatedEvent(draft=draft.model_copy(deep=True))]

        if isinstance(command, FinalizeCharacterCommand):
            draft = self._draft(command.draft_id)
            return self._finalize(draft, command.start_location_id)

        raise CharacterCreationError(f"unsupported character command: {type(command).__name__}")
