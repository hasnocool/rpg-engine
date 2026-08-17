"""FastAPI + WebSocket transport for remote clients."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from rpg_engine.commands import Command, parse_command
from rpg_engine.content.loader import load_content_pack_async
from rpg_engine.engine import SimulationError
from rpg_engine.events import Event
from rpg_engine.models import WorldState
from rpg_engine.persistence.sqlite import SQLiteEventStore
from rpg_engine.service import CampaignService


class CampaignCreateRequest(BaseModel):
    seed: int
    campaign_id: str | None = None


class EventEnvelope(BaseModel):
    events: list[dict[str, object]] = Field(default_factory=list)


class ConnectionHub:
    def __init__(self) -> None:
        self._connections: defaultdict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._broadcast_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def connect(self, campaign_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[campaign_id].add(websocket)

    async def disconnect(self, campaign_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections[campaign_id].discard(websocket)

    async def broadcast(self, campaign_id: str, events: list[Event]) -> None:
        payload = {"events": [event.model_dump(mode="json") for event in events]}
        async with self._broadcast_locks[campaign_id]:
            async with self._lock:
                targets = tuple(self._connections[campaign_id])
            if not targets:
                return
            results = await asyncio.gather(
                *(websocket.send_json(payload) for websocket in targets),
                return_exceptions=True,
            )
            dead = [
                websocket
                for websocket, result in zip(targets, results, strict=True)
                if isinstance(result, BaseException)
            ]
            if dead:
                async with self._lock:
                    for websocket in dead:
                        self._connections[campaign_id].discard(websocket)


def create_app(
    *,
    database_path: Path | str = "rpg_engine.db",
    content_path: Path | str | None = None,
) -> FastAPI:
    store = SQLiteEventStore(database_path)
    hub = ConnectionHub()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await store.initialize()
        content = None
        if content_path is not None:
            content = await load_content_pack_async(Path(content_path))
        app.state.service = CampaignService(store, content=content)
        yield

    app = FastAPI(
        title="RPG Engine API",
        version="0.1.0",
        description="Authoritative headless deterministic RPG simulation API",
        lifespan=lifespan,
    )

    def service() -> CampaignService:
        return app.state.service

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/campaigns", response_model=WorldState)
    async def create_campaign(request: CampaignCreateRequest) -> WorldState:
        try:
            return await service().create_campaign(
                request.seed, campaign_id=request.campaign_id
            )
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/campaigns/{campaign_id}/state", response_model=WorldState)
    async def campaign_state(campaign_id: str) -> WorldState:
        try:
            return await service().state(campaign_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="campaign not found") from exc

    @app.get("/campaigns/{campaign_id}/events", response_model=EventEnvelope)
    async def campaign_events(
        campaign_id: str, after: int = Query(default=0, ge=0)
    ) -> EventEnvelope:
        try:
            events = await service().events(campaign_id, after_sequence=after)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="campaign not found") from exc
        return EventEnvelope(events=[event.model_dump(mode="json") for event in events])

    @app.post("/campaigns/{campaign_id}/commands", response_model=EventEnvelope)
    async def execute_command(campaign_id: str, command: Command) -> EventEnvelope:
        try:
            events = await service().execute(campaign_id, command)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="campaign not found") from exc
        except SimulationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        await hub.broadcast(campaign_id, events)
        return EventEnvelope(events=[event.model_dump(mode="json") for event in events])

    @app.websocket("/campaigns/{campaign_id}/ws")
    async def campaign_socket(websocket: WebSocket, campaign_id: str) -> None:
        await hub.connect(campaign_id, websocket)
        try:
            await service().state(campaign_id)
            while True:
                payload = await websocket.receive_json()
                try:
                    command = parse_command(payload)
                    events = await service().execute(campaign_id, command)
                    await hub.broadcast(campaign_id, events)
                except (SimulationError, ValueError) as exc:
                    await websocket.send_json({"error": str(exc)})
        except (KeyError, WebSocketDisconnect):
            return
        finally:
            await hub.disconnect(campaign_id, websocket)

    return app


app = create_app()
