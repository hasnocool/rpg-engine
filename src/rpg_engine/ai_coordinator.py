"""Non-blocking async orchestration for AI providers, narration, and command execution."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from rpg_engine.ai_observations import AiObservation, build_ai_observation
from rpg_engine.ai_protocols import (
    AICommandDecision,
    AICommandProvider,
    NarrationRequest,
    NarrationResult,
    Narrator,
)
from rpg_engine.commands import Command
from rpg_engine.content.models import ContentRegistry
from rpg_engine.events import Event
from rpg_engine.models import WorldState

StateLoader = Callable[[str], Awaitable[WorldState]]
CommandExecutor = Callable[[str, Command], Awaitable[Sequence[Event]]]


@dataclass(frozen=True, slots=True)
class AITurnResult:
    observation: AiObservation
    decision: AICommandDecision
    events: tuple[Event, ...]
    narration: NarrationResult | None = None


class AIGameMasterCoordinator:
    """Serializes AI decisions per actor while delegating authority to async campaign services."""

    def __init__(self, *, provider_timeout_seconds: float = 30.0) -> None:
        if provider_timeout_seconds <= 0:
            raise ValueError("provider_timeout_seconds must be positive")
        self.provider_timeout_seconds = provider_timeout_seconds
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def _lock_for(self, campaign_id: str, actor_id: str) -> asyncio.Lock:
        key = (campaign_id, actor_id)
        async with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    async def run_turn(
        self,
        *,
        campaign_id: str,
        actor_id: str,
        content: ContentRegistry,
        provider: AICommandProvider,
        state_loader: StateLoader,
        command_executor: CommandExecutor,
        narrator: Narrator | None = None,
        memory_limit: int = 12,
    ) -> AITurnResult:
        lock = await self._lock_for(campaign_id, actor_id)
        async with lock:
            world = await state_loader(campaign_id)
            observation = build_ai_observation(
                world,
                content,
                actor_id=actor_id,
                memory_limit=memory_limit,
            )
            async with asyncio.timeout(self.provider_timeout_seconds):
                decision = await provider.propose(observation)

            events: tuple[Event, ...] = ()
            narration: NarrationResult | None = None
            if decision.command is not None:
                emitted = await command_executor(campaign_id, decision.command)
                events = tuple(emitted)

            if narrator is not None:
                latest_world = await state_loader(campaign_id)
                latest_observation = build_ai_observation(
                    latest_world,
                    content,
                    actor_id=actor_id,
                    memory_limit=memory_limit,
                )
                async with asyncio.timeout(self.provider_timeout_seconds):
                    narration = await narrator.narrate(
                        NarrationRequest(
                            observation=latest_observation,
                            events=events,
                        )
                    )
            return AITurnResult(
                observation=observation,
                decision=decision,
                events=events,
                narration=narration,
            )
