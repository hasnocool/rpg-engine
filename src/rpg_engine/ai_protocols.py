"""Asynchronous protocol contracts for AI command providers and narrators."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from rpg_engine.ai_observations import AiObservation
from rpg_engine.commands import Command
from rpg_engine.events import Event


@dataclass(frozen=True, slots=True)
class AICommandDecision:
    """One advisory provider result. Engine validation remains authoritative."""

    command: Command | None
    rationale: str = ""
    confidence: float = 1.0
    scores: tuple[tuple[str, float], ...] = field(default_factory=tuple)


class AICommandProvider(Protocol):
    """Non-blocking provider contract for local, remote, scripted, or model-backed agents."""

    name: str

    async def propose(self, observation: AiObservation) -> AICommandDecision: ...


@dataclass(frozen=True, slots=True)
class NarrationRequest:
    observation: AiObservation
    events: Sequence[Event] = field(default_factory=tuple)
    style_hint: str | None = None


@dataclass(frozen=True, slots=True)
class NarrationResult:
    text: str
    provider: str
    authoritative: bool = False


class Narrator(Protocol):
    """Narration is descriptive only and cannot mutate simulation state."""

    name: str

    async def narrate(self, request: NarrationRequest) -> NarrationResult: ...
