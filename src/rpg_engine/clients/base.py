"""Transport-neutral client protocol used by terminal and TUI frontends."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from rpg_engine.commands import Command
from rpg_engine.events import Event
from rpg_engine.models import WorldState
from rpg_engine.observations import CampaignObservation


class CampaignClient(Protocol):
    campaign_id: str

    async def state(self) -> WorldState: ...

    async def observation(self, *, actor_id: str | None = None) -> CampaignObservation: ...

    async def events(self, *, after_sequence: int = 0) -> list[Event]: ...

    async def execute(self, command: Command) -> list[Event]: ...

    def stream_events(self, *, after_sequence: int = 0) -> AsyncIterator[list[Event]]: ...

    async def close(self) -> None: ...
