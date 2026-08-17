"""Commands are player/AI intent. They never mutate game state directly."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from rpg_engine.models import Ability, Entity, Position, StrictModel
from rpg_engine.timeline import TimelineItemKind, TimelinePayload, TimeMode


class CreateEntityCommand(StrictModel):
    type: Literal["create_entity"] = "create_entity"
    entity: Entity


class MoveActorCommand(StrictModel):
    type: Literal["move_actor"] = "move_actor"
    actor_id: str
    position: Position


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


Command = Annotated[
    CreateEntityCommand
    | MoveActorCommand
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
    | ConfigureTimelineCommand
    | ScheduleTimelineItemCommand
    | CancelTimelineItemCommand
    | AdvanceTimelineCommand
    | AdvanceTimelineTurnCommand
    | SyncTimelineCommand
    | SetTimelinePausedCommand
    | DrainTimelineCommand,
    Field(discriminator="type"),
]

COMMAND_ADAPTER: TypeAdapter[Command] = TypeAdapter(Command)


def parse_command(payload: object) -> Command:
    return COMMAND_ADAPTER.validate_python(payload)
