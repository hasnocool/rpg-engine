"""Versioned FastAPI + resumable WebSocket transport for remote clients."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from rpg_engine import __version__
from rpg_engine.api.contracts import (
    ApiInfo,
    CampaignCreateRequest,
    EventEnvelope,
    ObservationEnvelope,
    StateEnvelope,
)
from rpg_engine.character_creation import CharacterCreationCatalog
from rpg_engine.character_web import CHARACTER_CREATOR_HTML
from rpg_engine.commands import Command, parse_command
from rpg_engine.content.loader import load_content_pack_async
from rpg_engine.engine import SimulationError
from rpg_engine.events import Event
from rpg_engine.models import WorldState
from rpg_engine.observations import CampaignObservation
from rpg_engine.persistence.sqlite import SQLiteEventStore
from rpg_engine.service import CampaignService
from rpg_engine.visuals import (
    VisualBindingManifest,
    load_visual_bindings_async,
    presentation_hints_for_event,
    visual_snapshot_from_observation,
)
from rpg_engine.webclient import INDEX_HTML


def _event_envelope(campaign_id: str, events: list[Event], *, cursor: int) -> EventEnvelope:
    if events:
        return EventEnvelope(
            campaign_id=campaign_id,
            from_sequence=events[0].sequence,
            to_sequence=events[-1].sequence,
            events=[event.model_dump(mode="json") for event in events],
        )
    return EventEnvelope(
        campaign_id=campaign_id,
        from_sequence=cursor,
        to_sequence=cursor,
        heartbeat=True,
    )


def create_app(
    *,
    database_path: Path | str = "rpg_engine.db",
    content_path: Path | str | None = None,
    visual_bindings_path: Path | str | None = None,
    campaign_service: CampaignService | None = None,
) -> FastAPI:
    store = SQLiteEventStore(database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        bindings = VisualBindingManifest()
        if visual_bindings_path is not None:
            bindings = await load_visual_bindings_async(Path(visual_bindings_path))
        app.state.visual_bindings = bindings

        if campaign_service is not None:
            app.state.service = campaign_service
            yield
            return
        await store.initialize()
        content = None
        if content_path is not None:
            content = await load_content_pack_async(Path(content_path))
        app.state.service = CampaignService(store, content=content)
        yield

    app = FastAPI(
        title="RPG Engine API",
        version=__version__,
        description="Authoritative headless deterministic RPG simulation API",
        lifespan=lifespan,
    )
    v1 = APIRouter(prefix="/api/v1")

    def service() -> CampaignService:
        return app.state.service

    def visual_bindings() -> VisualBindingManifest:
        return app.state.visual_bindings

    async def state_for(campaign_id: str) -> WorldState:
        try:
            return await service().state(campaign_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="campaign not found") from exc

    async def observation_for(
        campaign_id: str, actor_id: str | None
    ) -> CampaignObservation:
        try:
            return await service().observation(campaign_id, actor_id=actor_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def events_for(campaign_id: str, after: int) -> list[Event]:
        try:
            return await service().events(campaign_id, after_sequence=after)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="campaign not found") from exc

    async def execute_for(campaign_id: str, command: Command) -> list[Event]:
        try:
            return await service().execute(campaign_id, command)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="campaign not found") from exc
        except SimulationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @v1.get("/health", response_model=ApiInfo, operation_id="v1_health")
    async def v1_health() -> ApiInfo:
        return ApiInfo(engine_version=__version__)

    @v1.get(
        "/character-creation/catalog",
        response_model=CharacterCreationCatalog,
        operation_id="v1_character_creation_catalog",
    )
    async def v1_character_creation_catalog() -> CharacterCreationCatalog:
        return await service().character_creation_catalog()

    @v1.post("/campaigns", response_model=StateEnvelope, operation_id="v1_create_campaign")
    async def v1_create_campaign(request: CampaignCreateRequest) -> StateEnvelope:
        try:
            state = await service().create_campaign(
                request.seed, campaign_id=request.campaign_id
            )
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return StateEnvelope(state=state)

    @v1.get(
        "/campaigns/{campaign_id}/state",
        response_model=StateEnvelope,
        operation_id="v1_campaign_state",
    )
    async def v1_campaign_state(campaign_id: str) -> StateEnvelope:
        return StateEnvelope(state=await state_for(campaign_id))

    @v1.get(
        "/campaigns/{campaign_id}/observation",
        response_model=ObservationEnvelope,
        operation_id="v1_campaign_observation",
    )
    async def v1_campaign_observation(
        campaign_id: str,
        actor_id: str | None = Query(default=None),
    ) -> ObservationEnvelope:
        return ObservationEnvelope(
            observation=await observation_for(campaign_id, actor_id)
        )

    @v1.get(
        "/campaigns/{campaign_id}/visual",
        operation_id="v1_campaign_visual",
    )
    async def v1_campaign_visual(
        campaign_id: str,
        actor_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        observation = await observation_for(campaign_id, actor_id)
        visual = visual_snapshot_from_observation(observation, visual_bindings())
        return {"visual": visual.model_dump(mode="json")}

    @v1.get(
        "/campaigns/{campaign_id}/presentation",
        operation_id="v1_campaign_presentation",
    )
    async def v1_campaign_presentation(
        campaign_id: str,
        after: int = Query(default=0, ge=0),
    ) -> dict[str, object]:
        events = await events_for(campaign_id, after)
        batches = [
            presentation_hints_for_event(event, visual_bindings()).model_dump(mode="json")
            for event in events
        ]
        return {"campaign_id": campaign_id, "batches": batches}

    @v1.get(
        "/campaigns/{campaign_id}/events",
        response_model=EventEnvelope,
        operation_id="v1_campaign_events",
    )
    async def v1_campaign_events(
        campaign_id: str,
        after: int = Query(default=0, ge=0),
    ) -> EventEnvelope:
        events = await events_for(campaign_id, after)
        return _event_envelope(campaign_id, events, cursor=after)

    @v1.post(
        "/campaigns/{campaign_id}/commands",
        response_model=EventEnvelope,
        operation_id="v1_execute_command",
    )
    async def v1_execute_command(campaign_id: str, command: Command) -> EventEnvelope:
        events = await execute_for(campaign_id, command)
        cursor = events[-1].sequence if events else (await state_for(campaign_id)).sequence
        return _event_envelope(campaign_id, events, cursor=cursor)

    async def websocket_session(
        websocket: WebSocket,
        campaign_id: str,
        after: int,
    ) -> None:
        await websocket.accept()
        try:
            await service().state(campaign_id)
        except KeyError:
            await websocket.send_json({"error": "campaign not found"})
            await websocket.close(code=4404)
            return

        send_lock = asyncio.Lock()

        async def send_json(payload: object) -> None:
            async with send_lock:
                await websocket.send_json(payload)

        async def send_events() -> None:
            cursor = after
            async for events in service().stream_events(
                campaign_id,
                after_sequence=after,
            ):
                if events:
                    cursor = events[-1].sequence
                await send_json(
                    _event_envelope(campaign_id, events, cursor=cursor).model_dump(mode="json")
                )

        async def receive_commands() -> None:
            while True:
                payload = await websocket.receive_json()
                command_payload = (
                    payload.get("command", payload) if isinstance(payload, dict) else payload
                )
                try:
                    command = parse_command(command_payload)
                    await service().execute(campaign_id, command)
                except (SimulationError, ValueError) as exc:
                    await send_json({"error": str(exc)})

        sender = asyncio.create_task(send_events())
        receiver = asyncio.create_task(receive_commands())
        try:
            done, pending = await asyncio.wait(
                {sender, receiver},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()
        except WebSocketDisconnect:
            return
        finally:
            sender.cancel()
            receiver.cancel()
            await asyncio.gather(sender, receiver, return_exceptions=True)

    @v1.websocket("/campaigns/{campaign_id}/events/ws")
    async def v1_campaign_socket(
        websocket: WebSocket,
        campaign_id: str,
        after: int = Query(default=0, ge=0),
    ) -> None:
        await websocket_session(websocket, campaign_id, after)

    app.include_router(v1)

    @app.get("/client", response_class=HTMLResponse, include_in_schema=False)
    async def browser_client() -> str:
        return INDEX_HTML

    @app.get("/character-creator", response_class=HTMLResponse, include_in_schema=False)
    async def character_creator() -> str:
        return CHARACTER_CREATOR_HTML

    @app.get("/health", deprecated=True)
    async def legacy_health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/campaigns", response_model=WorldState, deprecated=True)
    async def legacy_create_campaign(request: CampaignCreateRequest) -> WorldState:
        return (await v1_create_campaign(request)).state

    @app.get("/campaigns/{campaign_id}/state", response_model=WorldState, deprecated=True)
    async def legacy_campaign_state(campaign_id: str) -> WorldState:
        return await state_for(campaign_id)

    @app.get("/campaigns/{campaign_id}/events", deprecated=True)
    async def legacy_campaign_events(
        campaign_id: str,
        after: int = Query(default=0, ge=0),
    ) -> dict[str, list[dict[str, object]]]:
        events = await events_for(campaign_id, after)
        return {"events": [event.model_dump(mode="json") for event in events]}

    @app.post("/campaigns/{campaign_id}/commands", deprecated=True)
    async def legacy_execute_command(
        campaign_id: str, command: Command
    ) -> dict[str, list[dict[str, object]]]:
        events = await execute_for(campaign_id, command)
        return {"events": [event.model_dump(mode="json") for event in events]}

    @app.websocket("/campaigns/{campaign_id}/ws")
    async def legacy_campaign_socket(websocket: WebSocket, campaign_id: str) -> None:
        await websocket_session(websocket, campaign_id, 0)

    return app


app = create_app()
