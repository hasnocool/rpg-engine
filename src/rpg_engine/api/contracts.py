"""Stable v1 transport contracts shared by REST, WebSocket, and clients."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from rpg_engine.models import WorldState
from rpg_engine.observations import CampaignObservation

API_VERSION = "v1"
SCHEMA_VERSION = 1


class CampaignCreateRequest(BaseModel):
    seed: int
    campaign_id: str | None = None


class StateEnvelope(BaseModel):
    schema_version: Literal[1] = 1
    api_version: Literal["v1"] = "v1"
    state: WorldState


class ObservationEnvelope(BaseModel):
    schema_version: Literal[1] = 1
    api_version: Literal["v1"] = "v1"
    observation: CampaignObservation


class EventEnvelope(BaseModel):
    schema_version: Literal[1] = 1
    api_version: Literal["v1"] = "v1"
    campaign_id: str
    from_sequence: int
    to_sequence: int
    events: list[dict[str, Any]] = Field(default_factory=list)
    heartbeat: bool = False


class ApiInfo(BaseModel):
    api_version: Literal["v1"] = "v1"
    schema_version: Literal[1] = 1
    engine_version: str
