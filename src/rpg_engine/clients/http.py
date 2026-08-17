"""Async HTTP client for the stable v1 campaign API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import websockets

from rpg_engine.commands import Command
from rpg_engine.events import Event, parse_event
from rpg_engine.models import WorldState
from rpg_engine.observations import CampaignObservation
from rpg_engine.visuals import VisualSnapshot


class HttpCampaignClient:
    def __init__(
        self,
        base_url: str,
        campaign_id: str,
        *,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.campaign_id = campaign_id
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def state(self) -> WorldState:
        response = await self._client.get(f"/api/v1/campaigns/{self.campaign_id}/state")
        response.raise_for_status()
        return WorldState.model_validate(response.json()["state"])

    async def observation(self, *, actor_id: str | None = None) -> CampaignObservation:
        params = {"actor_id": actor_id} if actor_id is not None else None
        response = await self._client.get(
            f"/api/v1/campaigns/{self.campaign_id}/observation", params=params
        )
        response.raise_for_status()
        return CampaignObservation.model_validate(response.json()["observation"])

    async def visual(self, *, actor_id: str | None = None) -> VisualSnapshot:
        params = {"actor_id": actor_id} if actor_id is not None else None
        response = await self._client.get(
            f"/api/v1/campaigns/{self.campaign_id}/visual", params=params
        )
        response.raise_for_status()
        return VisualSnapshot.model_validate(response.json()["visual"])

    async def events(self, *, after_sequence: int = 0) -> list[Event]:
        response = await self._client.get(
            f"/api/v1/campaigns/{self.campaign_id}/events",
            params={"after": after_sequence},
        )
        response.raise_for_status()
        return [parse_event(payload) for payload in response.json()["events"]]

    async def execute(self, command: Command) -> list[Event]:
        response = await self._client.post(
            f"/api/v1/campaigns/{self.campaign_id}/commands",
            json=command.model_dump(mode="json"),
        )
        response.raise_for_status()
        return [parse_event(payload) for payload in response.json()["events"]]

    async def stream_events(self, *, after_sequence: int = 0) -> AsyncIterator[list[Event]]:
        ws_base = self.base_url
        if ws_base.startswith("https://"):
            ws_base = "wss://" + ws_base.removeprefix("https://")
        elif ws_base.startswith("http://"):
            ws_base = "ws://" + ws_base.removeprefix("http://")
        uri = (
            f"{ws_base}/api/v1/campaigns/{self.campaign_id}/events/ws"
            f"?after={after_sequence}"
        )
        async with websockets.connect(uri) as websocket:
            async for message in websocket:
                payload = json.loads(message)
                if payload.get("heartbeat"):
                    yield []
                    continue
                yield [parse_event(event) for event in payload.get("events", [])]

    async def close(self) -> None:
        await self._client.aclose()
