"""In-process client adapter used by SSH and embedded frontends."""

from __future__ import annotations

from collections.abc import AsyncIterator

from rpg_engine.commands import Command
from rpg_engine.events import Event
from rpg_engine.models import WorldState
from rpg_engine.observations import CampaignObservation
from rpg_engine.service import CampaignService
from rpg_engine.visuals import VisualSnapshot


class LocalCampaignClient:
    def __init__(self, service: CampaignService, campaign_id: str) -> None:
        self.service = service
        self.campaign_id = campaign_id

    async def state(self) -> WorldState:
        return await self.service.state(self.campaign_id)

    async def observation(self, *, actor_id: str | None = None) -> CampaignObservation:
        return await self.service.observation(self.campaign_id, actor_id=actor_id)

    async def visual(self, *, actor_id: str | None = None) -> VisualSnapshot:
        return await self.service.visual(self.campaign_id, actor_id=actor_id)

    async def events(self, *, after_sequence: int = 0) -> list[Event]:
        return await self.service.events(self.campaign_id, after_sequence=after_sequence)

    async def execute(self, command: Command) -> list[Event]:
        return await self.service.execute(self.campaign_id, command)

    async def stream_events(self, *, after_sequence: int = 0) -> AsyncIterator[list[Event]]:
        async for events in self.service.stream_events(
            self.campaign_id, after_sequence=after_sequence
        ):
            yield events

    async def close(self) -> None:
        return None
