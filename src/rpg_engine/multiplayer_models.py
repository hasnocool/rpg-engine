"""Typed hosted-multiplayer contracts for v0.8."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from rpg_engine.commands import Command
from rpg_engine.models import StrictModel


class CampaignRole(StrEnum):
    OWNER = "owner"
    PLAYER = "player"
    SPECTATOR = "spectator"


class PartyRole(StrEnum):
    LEADER = "leader"
    MEMBER = "member"


class PlayerAccount(StrictModel):
    player_id: str
    display_name: str
    created_at: float


class AuthSession(StrictModel):
    session_id: str
    player_id: str
    expires_at: float


class AuthPrincipal(StrictModel):
    player_id: str
    display_name: str
    session_id: str
    expires_at: float


class CampaignMembership(StrictModel):
    campaign_id: str
    player_id: str
    role: CampaignRole
    controlled_actor_ids: set[str] = Field(default_factory=set)
    party_id: str | None = None
    joined_at: float


class Party(StrictModel):
    party_id: str
    campaign_id: str
    name: str
    owner_player_id: str
    created_at: float


class PartyMember(StrictModel):
    party_id: str
    player_id: str
    role: PartyRole
    joined_at: float


class MultiplayerCommandEnvelope(StrictModel):
    client_command_id: str = Field(min_length=1, max_length=128)
    command: Command


class CommandReceiptStatus(StrEnum):
    PENDING = "pending"
    COMMITTED = "committed"
    FAILED = "failed"


class CommandReceipt(StrictModel):
    campaign_id: str
    player_id: str
    client_command_id: str
    command_hash: str
    status: CommandReceiptStatus
    first_sequence: int | None = None
    last_sequence: int | None = None
    events: list[dict[str, object]] = Field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    created_at: float
    updated_at: float
    pending_until: float | None = None


class CommandClaim(StrictModel):
    state: Literal["claimed", "replay", "pending", "conflict"]
    execution_token: str | None = None
    receipt: CommandReceipt | None = None


class MultiplayerCommandResult(StrictModel):
    client_command_id: str
    replayed: bool = False
    first_sequence: int | None = None
    last_sequence: int | None = None
    events: list[dict[str, object]] = Field(default_factory=list)


class RateLimitDecision(StrictModel):
    allowed: bool
    remaining: int = 0
    retry_after_seconds: float = 0.0
    reset_at: float


class NodeRegistration(StrictModel):
    node_id: str
    public_url: str
    last_seen_at: float
    expires_at: float


class CampaignPlacement(StrictModel):
    campaign_id: str
    node_id: str
    public_url: str
    lease_until: float
    epoch: int


class EventStreamEnvelope(StrictModel):
    kind: Literal["events", "heartbeat"]
    cursor: int
    events: list[dict[str, object]] = Field(default_factory=list)


class HostedCampaignInfo(StrictModel):
    campaign_id: str
    seed: int
    membership: CampaignMembership
    placement: CampaignPlacement
