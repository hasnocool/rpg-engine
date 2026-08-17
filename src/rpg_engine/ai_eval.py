"""Offline deterministic evaluation harness for AI command providers."""

from __future__ import annotations

import json
from dataclasses import dataclass

from rpg_engine.ai_observations import build_ai_observation
from rpg_engine.ai_protocols import AICommandProvider
from rpg_engine.content.models import ContentRegistry
from rpg_engine.models import WorldState


@dataclass(frozen=True, slots=True)
class BenchmarkScenario:
    id: str
    world: WorldState
    content: ContentRegistry
    actor_id: str
    expected_command_types: frozenset[str]
    repeats: int = 2


@dataclass(frozen=True, slots=True)
class BenchmarkCaseResult:
    scenario_id: str
    passed: bool
    deterministic: bool
    command_type: str | None
    fingerprints: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkSuiteResult:
    provider_name: str
    cases: tuple[BenchmarkCaseResult, ...]

    @property
    def passed(self) -> int:
        return sum(case.passed for case in self.cases)

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def deterministic(self) -> bool:
        return all(case.deterministic for case in self.cases)

    @property
    def score(self) -> float:
        return 0.0 if not self.cases else self.passed / self.total


def decision_fingerprint(decision: object) -> str:
    command = getattr(decision, "command", None)
    payload = None if command is None else command.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


async def evaluate_provider(
    provider: AICommandProvider,
    scenarios: list[BenchmarkScenario],
) -> BenchmarkSuiteResult:
    """Evaluate task fit plus repeatability without network, clock, or mutable global state."""

    cases: list[BenchmarkCaseResult] = []
    for scenario in scenarios:
        if scenario.repeats < 2:
            raise ValueError("benchmark scenarios require at least two repeats")
        fingerprints: list[str] = []
        command_type: str | None = None
        for _ in range(scenario.repeats):
            world = scenario.world.model_copy(deep=True)
            content = scenario.content.model_copy(deep=True)
            observation = build_ai_observation(
                world,
                content,
                actor_id=scenario.actor_id,
            )
            decision = await provider.propose(observation)
            fingerprints.append(decision_fingerprint(decision))
            if decision.command is not None:
                command_type = decision.command.type
        deterministic = len(set(fingerprints)) == 1
        passed = command_type in scenario.expected_command_types and deterministic
        cases.append(
            BenchmarkCaseResult(
                scenario_id=scenario.id,
                passed=passed,
                deterministic=deterministic,
                command_type=command_type,
                fingerprints=tuple(fingerprints),
            )
        )
    return BenchmarkSuiteResult(provider_name=provider.name, cases=tuple(cases))
