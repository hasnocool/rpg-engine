"""Commands are player/AI intent. They never mutate game state directly."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from rpg_engine.models import (
    Ability,
    AiEncounterProposal,
    AiQuestProposal,
    Entity,
    Position,
    StrictModel,
)
from rpg_engine.timeline import TimelineItemKind, TimelinePayload, TimeMode


class CreateEntityCommand(StrictModel):
    type: Literal["create_entity"] = "create_entity"
    entity: Entity


class SpawnNpcCommand(StrictModel):
    type: Literal["spawn_npc"] = "spawn_npc"
    template_id: str
    entity_id: str
    location_id: str


class MoveActorCommand(StrictModel):
    type: Literal["move_actor"] = "move_actor"
    actor_id: str
    position: Position


class ExploreLocationCommand(StrictModel):
    type: Literal["explore_location"] = "explore_location"
    actor_id: str


class SearchLocationCommand(StrictModel):
    type: Literal["search_location"] = "search_location"
    actor_id: str
    ability: Ability = Ability.WISDOM


class TravelCommand(StrictModel):
    type: Literal["travel"] = "travel"
    actor_id: str
    destination_id: str


class RollCheckCommand(StrictModel):
    type: Literal["roll_check"] = "roll_check"
    actor_id: str
    ability: Ability
    dc: int
    stream: str | None = None


class RollSavingThrowCommand(StrictModel):
    type: Literal["roll_saving_throw"] = "roll_saving_throw"
    actor_id: str
    ability: Ability
    dc: int
    source_id: str | None = None
    stream: str | None = None


class AttackTargetCommand(StrictModel):
    type: Literal["attack_target"] = "attack_target"
    attacker_id: str
    target_id: str
    weapon_id: str = "unarmed"


class ApplyEffectCommand(StrictModel):
    type: Literal["apply_effect"] = "apply_effect"
    effect_id: str
    target_id: str
    source_id: str | None = None


class ApplyAreaEffectCommand(StrictModel):
    type: Literal["apply_area_effect"] = "apply_area_effect"
    effect_id: str
    source_id: str | None = None
    origin: Position | None = None
    candidate_ids: list[str] | None = None


class StartEncounterCommand(StrictModel):
    type: Literal["start_encounter"] = "start_encounter"
    encounter_id: str
    participant_ids: list[str] = Field(min_length=2)


class EndEncounterCommand(StrictModel):
    type: Literal["end_encounter"] = "end_encounter"
    encounter_id: str


class AdvanceTimeCommand(StrictModel):
    type: Literal["advance_time"] = "advance_time"
    minutes: int = Field(gt=0, le=60 * 24 * 365)


class EndTurnCommand(StrictModel):
    type: Literal["end_turn"] = "end_turn"
    actor_id: str
    encounter_id: str | None = None


class UseReactionCommand(StrictModel):
    type: Literal["use_reaction"] = "use_reaction"
    actor_id: str
    trigger_id: str
    reaction_id: str


class LootContainerCommand(StrictModel):
    type: Literal["loot_container"] = "loot_container"
    actor_id: str
    container_id: str
    item_ids: list[str] | None = None
    take_currency: bool = True


class EquipItemCommand(StrictModel):
    type: Literal["equip_item"] = "equip_item"
    actor_id: str
    item_id: str


class UnequipItemCommand(StrictModel):
    type: Literal["unequip_item"] = "unequip_item"
    actor_id: str
    item_id: str


class StartDialogueCommand(StrictModel):
    type: Literal["start_dialogue"] = "start_dialogue"
    actor_id: str
    npc_id: str
    dialogue_id: str | None = None


class ChooseDialogueOptionCommand(StrictModel):
    type: Literal["choose_dialogue_option"] = "choose_dialogue_option"
    actor_id: str
    session_id: str
    option_id: str


class StartQuestCommand(StrictModel):
    type: Literal["start_quest"] = "start_quest"
    actor_id: str
    quest_id: str


class AdvanceQuestCommand(StrictModel):
    type: Literal["advance_quest"] = "advance_quest"
    actor_id: str
    quest_id: str
    trigger: str


class BuyItemCommand(StrictModel):
    type: Literal["buy_item"] = "buy_item"
    actor_id: str
    merchant_id: str
    item_id: str
    quantity: int = Field(default=1, ge=1, le=1000)


class SellItemCommand(StrictModel):
    type: Literal["sell_item"] = "sell_item"
    actor_id: str
    merchant_id: str
    item_id: str
    quantity: int = Field(default=1, ge=1, le=1000)


class ConfigureTimelineCommand(StrictModel):
    type: Literal["configure_timeline"] = "configure_timeline"
    mode: TimeMode
    turn_quantum_ms: int | None = Field(default=None, gt=0)
    turn_timeout_ms: int | None = Field(default=None, gt=0)


class ScheduleTimelineItemCommand(StrictModel):
    type: Literal["schedule_timeline_item"] = "schedule_timeline_item"
    item_id: str
    kind: TimelineItemKind
    delay_ms: int | None = Field(default=None, ge=0)
    due_ms: int | None = Field(default=None, ge=0)
    priority: int = 0
    actor_id: str | None = None
    payload: TimelinePayload = Field(default_factory=dict)
    interval_ms: int | None = Field(default=None, gt=0)
    remaining_occurrences: int | None = Field(default=None, gt=0)
    replace: bool = False

    @model_validator(mode="after")
    def validate_due_time(self) -> ScheduleTimelineItemCommand:
        if self.delay_ms is not None and self.due_ms is not None:
            raise ValueError("provide delay_ms or due_ms, not both")
        return self


class CancelTimelineItemCommand(StrictModel):
    type: Literal["cancel_timeline_item"] = "cancel_timeline_item"
    item_id: str


class AdvanceTimelineCommand(StrictModel):
    type: Literal["advance_timeline"] = "advance_timeline"
    delta_ms: int = Field(gt=0)
    max_firings: int = Field(default=10_000, gt=0, le=100_000)


class AdvanceTimelineTurnCommand(StrictModel):
    type: Literal["advance_timeline_turn"] = "advance_timeline_turn"
    turns: int = Field(default=1, gt=0, le=10_000)
    max_firings: int = Field(default=10_000, gt=0, le=100_000)


class SyncTimelineCommand(StrictModel):
    type: Literal["sync_timeline"] = "sync_timeline"
    wall_time_ms: int = Field(ge=0)
    max_firings: int = Field(default=10_000, gt=0, le=100_000)


class SetTimelinePausedCommand(StrictModel):
    type: Literal["set_timeline_paused"] = "set_timeline_paused"
    paused: bool
    wall_time_ms: int | None = Field(default=None, ge=0)
    max_firings: int = Field(default=10_000, gt=0, le=100_000)


class DrainTimelineCommand(StrictModel):
    type: Literal["drain_timeline"] = "drain_timeline"
    max_firings: int = Field(default=10_000, gt=0, le=100_000)


class InitializeLivingWorldCommand(StrictModel):
    type: Literal["initialize_living_world"] = "initialize_living_world"


class AdjustFactionRelationCommand(StrictModel):
    type: Literal["adjust_faction_relation"] = "adjust_faction_relation"
    faction_a_id: str
    faction_b_id: str
    delta: int = Field(ge=-200, le=200)
    reason: str = "command"


class AdjustReputationCommand(StrictModel):
    type: Literal["adjust_reputation"] = "adjust_reputation"
    actor_id: str
    faction_id: str
    delta: int = Field(ge=-200, le=200)
    reason: str = "command"


class ResolveOffscreenEncounterCommand(StrictModel):
    type: Literal["resolve_offscreen_encounter"] = "resolve_offscreen_encounter"
    encounter_id: str
    attacker_ids: list[str] = Field(min_length=1)
    defender_ids: list[str] = Field(min_length=1)
    location_id: str | None = None


class GenerateRumorCommand(StrictModel):
    type: Literal["generate_rumor"] = "generate_rumor"
    location_id: str | None = None
    template_id: str | None = None


class GenerateDynamicQuestCommand(StrictModel):
    type: Literal["generate_dynamic_quest"] = "generate_dynamic_quest"
    origin_location_id: str
    template_id: str | None = None


class CompleteDynamicQuestCommand(StrictModel):
    type: Literal["complete_dynamic_quest"] = "complete_dynamic_quest"
    actor_id: str
    quest_id: str


class HarvestResourceCommand(StrictModel):
    type: Literal["harvest_resource"] = "harvest_resource"
    actor_id: str
    node_id: str
    amount: int = Field(default=1, gt=0, le=1000)


class RecordNpcMemoryCommand(StrictModel):
    type: Literal["record_npc_memory"] = "record_npc_memory"
    actor_id: str
    memory_id: str
    summary: str = Field(min_length=1, max_length=2000)
    importance: int = Field(default=50, ge=0, le=100)
    tags: set[str] = Field(default_factory=set)
    subject_ids: set[str] = Field(default_factory=set)
    expires_after_minutes: int | None = Field(default=None, gt=0)


class ForgetNpcMemoryCommand(StrictModel):
    type: Literal["forget_npc_memory"] = "forget_npc_memory"
    actor_id: str
    memory_id: str
    reason: str = "explicit_forget"


class SubmitAiEncounterProposalCommand(StrictModel):
    type: Literal["submit_ai_encounter_proposal"] = "submit_ai_encounter_proposal"
    proposal: AiEncounterProposal
    activate: bool = False


class SubmitAiQuestProposalCommand(StrictModel):
    type: Literal["submit_ai_quest_proposal"] = "submit_ai_quest_proposal"
    proposal: AiQuestProposal
    activate: bool = False


class ActivateAiProposalCommand(StrictModel):
    type: Literal["activate_ai_proposal"] = "activate_ai_proposal"
    proposal_id: str


Command = Annotated[
    CreateEntityCommand
    | SpawnNpcCommand
    | MoveActorCommand
    | ExploreLocationCommand
    | SearchLocationCommand
    | TravelCommand
    | RollCheckCommand
    | RollSavingThrowCommand
    | AttackTargetCommand
    | ApplyEffectCommand
    | ApplyAreaEffectCommand
    | StartEncounterCommand
    | EndEncounterCommand
    | AdvanceTimeCommand
    | EndTurnCommand
    | UseReactionCommand
    | LootContainerCommand
    | EquipItemCommand
    | UnequipItemCommand
    | StartDialogueCommand
    | ChooseDialogueOptionCommand
    | StartQuestCommand
    | AdvanceQuestCommand
    | BuyItemCommand
    | SellItemCommand
    | ConfigureTimelineCommand
    | ScheduleTimelineItemCommand
    | CancelTimelineItemCommand
    | AdvanceTimelineCommand
    | AdvanceTimelineTurnCommand
    | SyncTimelineCommand
    | SetTimelinePausedCommand
    | DrainTimelineCommand
    | InitializeLivingWorldCommand
    | AdjustFactionRelationCommand
    | AdjustReputationCommand
    | ResolveOffscreenEncounterCommand
    | GenerateRumorCommand
    | GenerateDynamicQuestCommand
    | CompleteDynamicQuestCommand
    | HarvestResourceCommand
    | RecordNpcMemoryCommand
    | ForgetNpcMemoryCommand
    | SubmitAiEncounterProposalCommand
    | SubmitAiQuestProposalCommand
    | ActivateAiProposalCommand,
    Field(discriminator="type"),
]

COMMAND_ADAPTER = TypeAdapter(Command)


def parse_command(payload: object) -> Command:
    return COMMAND_ADAPTER.validate_python(payload)
