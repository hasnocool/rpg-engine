"""Deterministic utility-AI, behavior-tree, and narrator reference implementations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from rpg_engine.ai_observations import AiActorObservation, AiObservation
from rpg_engine.ai_protocols import (
    AICommandDecision,
    NarrationRequest,
    NarrationResult,
)
from rpg_engine.commands import (
    AttackTargetCommand,
    EndTurnCommand,
    ExploreLocationCommand,
)


@dataclass(frozen=True, slots=True)
class UtilityCandidate:
    label: str
    score: float
    decision: AICommandDecision


def _health_fraction(actor: AiActorObservation) -> float:
    if actor.health is None or actor.health.maximum <= 0:
        return 1.0
    return actor.health.current / actor.health.maximum


class UtilityAgent:
    """Small deterministic utility scorer useful as a baseline and fallback agent."""

    name = "utility-reference"

    def __init__(self, *, weapon_id: str = "unarmed") -> None:
        self.weapon_id = weapon_id

    def _candidates(self, observation: AiObservation) -> list[UtilityCandidate]:
        candidates: list[UtilityCandidate] = []
        encounter = observation.encounter
        if encounter is not None:
            if encounter.active_actor_id != observation.actor_id:
                return []
            participant_ids = set(encounter.participant_ids)
            targets = [
                actor
                for actor in observation.nearby_actors
                if actor.id in participant_ids
                and actor.health is not None
                and actor.health.current > 0
            ]
            for target in targets:
                score = 100.0 + (1.0 - _health_fraction(target)) * 20.0
                candidates.append(
                    UtilityCandidate(
                        label=f"attack:{target.id}",
                        score=score,
                        decision=AICommandDecision(
                            command=AttackTargetCommand(
                                attacker_id=observation.actor_id,
                                target_id=target.id,
                                weapon_id=self.weapon_id,
                            ),
                            rationale=f"attack active encounter target {target.id}",
                            confidence=min(1.0, score / 120.0),
                        ),
                    )
                )
            candidates.append(
                UtilityCandidate(
                    label="end_turn",
                    score=1.0,
                    decision=AICommandDecision(
                        command=EndTurnCommand(
                            actor_id=observation.actor_id,
                            encounter_id=encounter.id,
                        ),
                        rationale="no higher-value tactical action",
                        confidence=0.5,
                    ),
                )
            )
        elif observation.location is not None:
            candidates.append(
                UtilityCandidate(
                    label="explore",
                    score=10.0,
                    decision=AICommandDecision(
                        command=ExploreLocationCommand(actor_id=observation.actor_id),
                        rationale="explore the current known location",
                        confidence=0.7,
                    ),
                )
            )
        return candidates

    async def propose(self, observation: AiObservation) -> AICommandDecision:
        candidates = self._candidates(observation)
        if not candidates:
            return AICommandDecision(
                command=None,
                rationale="no valid reference action is currently available",
                confidence=1.0,
            )
        candidates.sort(key=lambda item: (-item.score, item.label))
        winner = candidates[0]
        scores = tuple((item.label, item.score) for item in candidates)
        return AICommandDecision(
            command=winner.decision.command,
            rationale=winner.decision.rationale,
            confidence=winner.decision.confidence,
            scores=scores,
        )


class BehaviorStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass(slots=True)
class BehaviorTreeContext:
    observation: AiObservation
    decision: AICommandDecision | None = None


class BehaviorNode(Protocol):
    async def tick(self, context: BehaviorTreeContext) -> BehaviorStatus: ...


class SelectorNode:
    def __init__(self, *children: BehaviorNode) -> None:
        self.children = children

    async def tick(self, context: BehaviorTreeContext) -> BehaviorStatus:
        for child in self.children:
            if await child.tick(context) == BehaviorStatus.SUCCESS:
                return BehaviorStatus.SUCCESS
        return BehaviorStatus.FAILURE


class SequenceNode:
    def __init__(self, *children: BehaviorNode) -> None:
        self.children = children

    async def tick(self, context: BehaviorTreeContext) -> BehaviorStatus:
        for child in self.children:
            if await child.tick(context) == BehaviorStatus.FAILURE:
                return BehaviorStatus.FAILURE
        return BehaviorStatus.SUCCESS


class ConditionNode:
    def __init__(self, predicate: Callable[[AiObservation], bool]) -> None:
        self.predicate = predicate

    async def tick(self, context: BehaviorTreeContext) -> BehaviorStatus:
        return (
            BehaviorStatus.SUCCESS
            if self.predicate(context.observation)
            else BehaviorStatus.FAILURE
        )


class DecisionNode:
    def __init__(self, builder: Callable[[AiObservation], AICommandDecision | None]) -> None:
        self.builder = builder

    async def tick(self, context: BehaviorTreeContext) -> BehaviorStatus:
        decision = self.builder(context.observation)
        if decision is None:
            return BehaviorStatus.FAILURE
        context.decision = decision
        return BehaviorStatus.SUCCESS


def _active_turn(observation: AiObservation) -> bool:
    return (
        observation.encounter is not None
        and observation.encounter.active_actor_id == observation.actor_id
    )


def _attack_weakest(observation: AiObservation) -> AICommandDecision | None:
    encounter = observation.encounter
    if encounter is None:
        return None
    participant_ids = set(encounter.participant_ids)
    targets = [
        actor
        for actor in observation.nearby_actors
        if actor.id in participant_ids
        and actor.health is not None
        and actor.health.current > 0
    ]
    if not targets:
        return AICommandDecision(
            command=EndTurnCommand(
                actor_id=observation.actor_id,
                encounter_id=encounter.id,
            ),
            rationale="behavior tree found no living visible target",
            confidence=1.0,
        )
    target = min(targets, key=lambda actor: (_health_fraction(actor), actor.id))
    return AICommandDecision(
        command=AttackTargetCommand(
            attacker_id=observation.actor_id,
            target_id=target.id,
            weapon_id="unarmed",
        ),
        rationale=f"behavior tree selected weakest visible target {target.id}",
        confidence=0.8,
    )


def _explore(observation: AiObservation) -> AICommandDecision | None:
    if observation.encounter is not None or observation.location is None:
        return None
    return AICommandDecision(
        command=ExploreLocationCommand(actor_id=observation.actor_id),
        rationale="behavior tree selected exploration",
        confidence=0.7,
    )


def reference_behavior_tree() -> BehaviorNode:
    """Reference tree: act in combat first, otherwise explore the current location."""

    return SelectorNode(
        SequenceNode(ConditionNode(_active_turn), DecisionNode(_attack_weakest)),
        DecisionNode(_explore),
    )


class BehaviorTreeAgent:
    name = "behavior-tree-reference"

    def __init__(self, root: BehaviorNode | None = None) -> None:
        self.root = root or reference_behavior_tree()

    async def propose(self, observation: AiObservation) -> AICommandDecision:
        context = BehaviorTreeContext(observation=observation)
        await self.root.tick(context)
        return context.decision or AICommandDecision(
            command=None,
            rationale="behavior tree produced no action",
            confidence=1.0,
        )


class DeterministicNarrator:
    """Reference narrator that describes authoritative facts without inventing new state."""

    name = "deterministic-narrator"

    async def narrate(self, request: NarrationRequest) -> NarrationResult:
        observation = request.observation
        parts = [f"{observation.self_actor.name} is at"]
        parts.append(observation.location.name if observation.location else "an unknown location")
        if observation.weather is not None:
            parts.append(f"under {observation.weather.condition} weather")
        if request.events:
            event_types = ", ".join(event.type for event in request.events[:4])
            parts.append(f"after {event_types}")
        if request.style_hint:
            parts.append(f"[{request.style_hint}]")
        return NarrationResult(text=" ".join(parts) + ".", provider=self.name)
