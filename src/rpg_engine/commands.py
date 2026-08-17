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


class AdvanceTimeCommand(StrictModel):
    type: Literal["advance_time"] = "advance_time"
    minutes: int = Field(gt=0, le=60 * 24 * 365)


class EndTurnCommand(StrictModel):
    type: Literal["end_turn"] = "end_turn"
    actor_id: str


Command = Annotated[
    CreateEntityCommand
    | MoveActorCommand
    | RollCheckCommand
    | AttackTargetCommand
    | ApplyEffectCommand
    | AdvanceTimeCommand
    | EndTurnCommand,
    Field(discriminator="type"),
]

COMMAND_ADAPTER = TypeAdapter(Command)


def parse_command(payload: object) -> Command:
    return COMMAND_ADAPTER.validate_python(payload)
