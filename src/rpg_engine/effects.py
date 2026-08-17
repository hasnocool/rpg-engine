"""Composable effect pipeline used by spells, items, abilities, and conditions."""

from __future__ import annotations

import ast
import operator
import re
from collections.abc import Callable, Mapping

from rpg_engine.content.models import EffectSpec
from rpg_engine.dice import DeterministicRNG
from rpg_engine.events import (
    ConditionAddedEvent,
    ConditionRemovedEvent,
    EventBase,
    HealingAppliedEvent,
)
from rpg_engine.models import Entity

_DICE_TOKEN_RE = re.compile(r"\b\d*d\d+\b", re.IGNORECASE)
_BIN_OPS: dict[type[ast.operator], object] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.FloorDiv: operator.floordiv,
}
_UNARY_OPS: dict[type[ast.unaryop], object] = {ast.UAdd: operator.pos, ast.USub: operator.neg}
DamageResolver = Callable[[Entity, Entity | None, str, int], list[EventBase]]


def _eval_numeric(node: ast.AST, variables: Mapping[str, int]) -> int:
    if isinstance(node, ast.Expression):
        return _eval_numeric(node.body, variables)
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.Name) and node.id in variables:
        return variables[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        func = _BIN_OPS[type(node.op)]
        left = _eval_numeric(node.left, variables)
        right = _eval_numeric(node.right, variables)
        return int(func(left, right))  # type: ignore[operator]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        func = _UNARY_OPS[type(node.op)]
        return int(func(_eval_numeric(node.operand, variables)))  # type: ignore[operator]
    raise ValueError("effect expression contains an unsupported operation")


def resolve_amount(
    expression: str,
    *,
    rng: DeterministicRNG,
    stream: str,
    variables: Mapping[str, int] | None = None,
) -> int:
    variables = variables or {}
    index = 0

    def replace_dice(match: re.Match[str]) -> str:
        nonlocal index
        index += 1
        return str(rng.roll(match.group(0), stream=f"{stream}:dice:{index}").total)

    expanded = _DICE_TOKEN_RE.sub(replace_dice, expression)
    tree = ast.parse(expanded, mode="eval")
    return _eval_numeric(tree, variables)


class EffectPipeline:
    def apply(
        self,
        effect: EffectSpec,
        *,
        target: Entity,
        source: Entity | None,
        rng: DeterministicRNG,
        damage_resolver: DamageResolver,
        variables: Mapping[str, int] | None = None,
    ) -> list[EventBase]:
        events: list[EventBase] = []
        for index, operation in enumerate(effect.operations):
            stream = f"effect:{effect.id}:{source.id if source else 'world'}:{target.id}:{index}"
            if operation.type == "damage":
                if not operation.amount:
                    raise ValueError("damage effect requires amount")
                raw_amount = max(
                    0,
                    resolve_amount(operation.amount, rng=rng, stream=stream, variables=variables),
                )
                events.extend(damage_resolver(target, source, operation.damage_type, raw_amount))
            elif operation.type == "heal":
                if target.health is None:
                    raise ValueError(f"target {target.id!r} has no health component")
                if not operation.amount:
                    raise ValueError("heal effect requires amount")
                amount = max(
                    0,
                    resolve_amount(operation.amount, rng=rng, stream=stream, variables=variables),
                )
                before = target.health.current
                target.health.current = min(target.health.maximum, target.health.current + amount)
                events.append(
                    HealingAppliedEvent(
                        source_id=source.id if source else None,
                        target_id=target.id,
                        amount=target.health.current - before,
                        hp_after=target.health.current,
                    )
                )
            elif operation.type == "add_condition":
                if not operation.condition:
                    raise ValueError("add_condition requires condition")
                target.conditions.add(operation.condition)
                events.append(
                    ConditionAddedEvent(
                        target_id=target.id, condition=operation.condition
                    )
                )
            elif operation.type == "remove_condition":
                if not operation.condition:
                    raise ValueError("remove_condition requires condition")
                target.conditions.discard(operation.condition)
                events.append(
                    ConditionRemovedEvent(
                        target_id=target.id, condition=operation.condition
                    )
                )
        return events
