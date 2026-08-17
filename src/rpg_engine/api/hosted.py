"""Authenticated v0.8 hosted multiplayer FastAPI/WebSocket adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from rpg_engine.models import WorldState
from rpg_engine.multiplayer import (
    AuthenticationError,
    AuthorizationError,
    CampaignRedirect,
    CommandInProgressError,
    HostedCampaignService,
    IdempotencyConflictError,
    MultiplayerError,
    RateLimitExceededError,
    ReplayedCommandError,
)
from rpg_engine.multiplayer_models import (
    AuthPrincipal,
    CampaignMembership,
    CampaignPlacement,
    CampaignRole,
    CommandReceipt,
    MultiplayerCommandEnvelope,
    MultiplayerCommandResult,
    Party,
    PartyMember,
    PlayerAccount,
)
from rpg_engine.multiplayer_store import MultiplayerStore
from rpg_engine.persistence.sqlite import SQLiteEventStore
from rpg_engine.service import CampaignService


class RegisterRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=10, max_length=1024)


class LoginRequest(BaseModel):
    player_id: str
    password: str = Field(min_length=1, max_length=1024)


class LoginResponse(BaseModel):
    principal: AuthPrincipal
    access_token: str
    token_type: str = "bearer"


class CampaignCreateRequest(BaseModel):
    seed: int
    campaign_id: str | None = None


class HostedCampaignResponse(BaseModel):
    world: WorldState
    placement: CampaignPlacement


class MembershipGrantRequest(BaseModel):
    player_id: str
    role: CampaignRole
    controlled_actor_ids: set[str] = Field(default_factory=set)
    party_id: str | None = None


class PartyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    party_id: str | None = None


class PartyMemberRequest(BaseModel):
    player_id: str


def _bearer_token(authorization: str | None) -> str:
    if authorization is None:
        raise AuthenticationError("missing bearer token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthenticationError("invalid authorization header")
    return token


def create_hosted_app(
    *,
    database_path: Path | str = "rpg_engine.db",
    node_id: str = "node-1",
    public_url: str = "http://127.0.0.1:8000",
) -> FastAPI:
    event_store = SQLiteEventStore(database_path)
    multiplayer_store = MultiplayerStore(database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await event_store.initialize()
        authority = CampaignService(event_store)
        hosted = HostedCampaignService(
            authority,
            multiplayer_store,
            node_id=node_id,
            public_url=public_url,
        )
        await hosted.start()
        app.state.hosted = hosted
        try:
            yield
        finally:
            await hosted.close()

    app = FastAPI(
        title="RPG Engine Hosted Multiplayer API",
        version="0.8.0",
        description="Authenticated authoritative multiplayer transport for rpg-engine",
        lifespan=lifespan,
    )

    def hosted() -> HostedCampaignService:
        return app.state.hosted

    @app.exception_handler(AuthenticationError)
    async def authentication_error(_: Request, exc: AuthenticationError) -> JSONResponse:
        return JSONResponse(status_code=401, content={"detail": str(exc)})

    @app.exception_handler(AuthorizationError)
    async def authorization_error(_: Request, exc: AuthorizationError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_error(_: Request, exc: IdempotencyConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(CommandInProgressError)
    async def command_pending(_: Request, exc: CommandInProgressError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ReplayedCommandError)
    async def replayed_failure(_: Request, exc: ReplayedCommandError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc), "replayed": True})

    @app.exception_handler(RateLimitExceededError)
    async def rate_limited(_: Request, exc: RateLimitExceededError) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"detail": str(exc)},
            headers={"Retry-After": str(max(1, int(exc.decision.retry_after_seconds)))},
        )

    @app.exception_handler(CampaignRedirect)
    async def campaign_redirect(request: Request, exc: CampaignRedirect) -> JSONResponse:
        target = f"{exc.placement.public_url}{request.url.path}"
        if request.url.query:
            target = f"{target}?{request.url.query}"
        return JSONResponse(
            status_code=307,
            content={"detail": str(exc), "placement": exc.placement.model_dump(mode="json")},
            headers={"Location": target},
        )

    @app.exception_handler(MultiplayerError)
    async def multiplayer_error(_: Request, exc: MultiplayerError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "node_id": node_id}

    @app.post("/v1/players", response_model=PlayerAccount)
    async def register(request: RegisterRequest) -> PlayerAccount:
        try:
            return await hosted().register_player(request.display_name, request.password)
        except Exception as exc:
            if "UNIQUE constraint" in str(exc):
                raise HTTPException(status_code=409, detail="player already exists") from exc
            raise

    @app.post("/v1/sessions", response_model=LoginResponse)
    async def login(request: LoginRequest) -> LoginResponse:
        principal, token = await hosted().login(request.player_id, request.password)
        return LoginResponse(principal=principal, access_token=token)

    @app.delete("/v1/sessions/current", status_code=204)
    async def logout(authorization: str | None = Header(default=None)) -> None:
        await hosted().logout(_bearer_token(authorization))

    @app.post("/v1/campaigns", response_model=HostedCampaignResponse)
    async def create_campaign(
        request: CampaignCreateRequest,
        authorization: str | None = Header(default=None),
    ) -> HostedCampaignResponse:
        world, placement = await hosted().create_campaign(
            _bearer_token(authorization),
            request.seed,
            campaign_id=request.campaign_id,
        )
        return HostedCampaignResponse(world=world, placement=placement)

    @app.get("/v1/campaigns/{campaign_id}/membership", response_model=CampaignMembership)
    async def membership(
        campaign_id: str,
        authorization: str | None = Header(default=None),
    ) -> CampaignMembership:
        return await hosted().membership(_bearer_token(authorization), campaign_id)

    @app.put("/v1/campaigns/{campaign_id}/members", response_model=CampaignMembership)
    async def grant_membership(
        campaign_id: str,
        request: MembershipGrantRequest,
        authorization: str | None = Header(default=None),
    ) -> CampaignMembership:
        return await hosted().grant_membership(
            _bearer_token(authorization),
            campaign_id,
            request.player_id,
            role=request.role,
            controlled_actor_ids=request.controlled_actor_ids,
            party_id=request.party_id,
        )

    @app.post("/v1/campaigns/{campaign_id}/parties", response_model=Party)
    async def create_party(
        campaign_id: str,
        request: PartyCreateRequest,
        authorization: str | None = Header(default=None),
    ) -> Party:
        return await hosted().create_party(
            _bearer_token(authorization),
            campaign_id,
            request.name,
            party_id=request.party_id,
        )

    @app.post("/v1/parties/{party_id}/members", response_model=PartyMember)
    async def add_party_member(
        party_id: str,
        request: PartyMemberRequest,
        authorization: str | None = Header(default=None),
    ) -> PartyMember:
        return await hosted().add_party_member(
            _bearer_token(authorization), party_id, request.player_id
        )

    @app.get("/v1/campaigns/{campaign_id}/placement", response_model=CampaignPlacement)
    async def placement(
        campaign_id: str,
        authorization: str | None = Header(default=None),
    ) -> CampaignPlacement:
        return await hosted().placement(_bearer_token(authorization), campaign_id)

    @app.get("/v1/campaigns/{campaign_id}/state", response_model=WorldState)
    async def state(
        campaign_id: str,
        authorization: str | None = Header(default=None),
    ) -> WorldState:
        return await hosted().state(_bearer_token(authorization), campaign_id)

    @app.post(
        "/v1/campaigns/{campaign_id}/commands", response_model=MultiplayerCommandResult
    )
    async def execute(
        campaign_id: str,
        envelope: MultiplayerCommandEnvelope,
        authorization: str | None = Header(default=None),
    ) -> MultiplayerCommandResult:
        return await hosted().execute(
            _bearer_token(authorization), campaign_id, envelope
        )

    @app.get(
        "/v1/campaigns/{campaign_id}/commands/{client_command_id}",
        response_model=CommandReceipt | None,
    )
    async def receipt(
        campaign_id: str,
        client_command_id: str,
        authorization: str | None = Header(default=None),
    ) -> CommandReceipt | None:
        return await hosted().receipt(
            _bearer_token(authorization), campaign_id, client_command_id
        )

    @app.get("/v1/campaigns/{campaign_id}/events")
    async def events(
        campaign_id: str,
        after: int = Query(default=0, ge=0),
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        batch = await hosted().event_batch(
            _bearer_token(authorization), campaign_id, after_sequence=after
        )
        return batch.model_dump(mode="json")

    @app.websocket("/v1/campaigns/{campaign_id}/events/ws")
    async def event_socket(
        websocket: WebSocket,
        campaign_id: str,
        token: str = Query(),
        after: int = Query(default=0, ge=0),
    ) -> None:
        try:
            stream = hosted().stream_events(token, campaign_id, after_sequence=after)
            await websocket.accept()
            async for envelope in stream:
                await websocket.send_json(envelope.model_dump(mode="json"))
        except CampaignRedirect as exc:
            await websocket.send_json(
                {
                    "kind": "redirect",
                    "public_url": exc.placement.public_url,
                    "placement": exc.placement.model_dump(mode="json"),
                }
            )
            await websocket.close(code=1012)
        except (AuthenticationError, AuthorizationError):
            await websocket.close(code=4403)
        except Exception:
            await websocket.close(code=1011)

    return app


app = create_hosted_app()
