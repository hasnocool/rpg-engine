"""Commands are player/AI intent. They never mutate game state directly."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from rpg_engine.models import Ability, Entity, Position, StrictModel


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
    | UseReactionCommand,
    Field(discriminator="type"),
]

COMMAND_ADAPTER = TypeAdapter(Command)


def parse_command(payload: object) -> Command:
    return COMMAND_ADAPTER.validate_python(payload)
