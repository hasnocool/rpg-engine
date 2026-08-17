"""Authoritative hosted multiplayer orchestration for v0.8."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Protocol

from rpg_engine.commands import Command
from rpg_engine.events import Event, parse_event
from rpg_engine.models import WorldState
from rpg_engine.multiplayer_models import (
    AuthPrincipal,
    CampaignMembership,
    CampaignPlacement,
    CampaignRole,
    CommandReceipt,
    CommandReceiptStatus,
    EventStreamEnvelope,
    MultiplayerCommandEnvelope,
    MultiplayerCommandResult,
    Party,
    PartyMember,
    PartyRole,
    PlayerAccount,
    RateLimitDecision,
)
from rpg_engine.multiplayer_store import MultiplayerStore


class MultiplayerError(RuntimeError):
    """Base hosted multiplayer error."""


class AuthenticationError(MultiplayerError):
    pass


class AuthorizationError(MultiplayerError):
    pass


class IdempotencyConflictError(MultiplayerError):
    pass


class CommandInProgressError(MultiplayerError):
    pass


class ReplayedCommandError(MultiplayerError):
    """A previously failed command was replayed with the same client command ID."""


class RateLimitExceededError(MultiplayerError):
    def __init__(self, decision: RateLimitDecision) -> None:
        super().__init__("rate limit exceeded")
        self.decision = decision


class CampaignRedirect(MultiplayerError):
    def __init__(self, placement: CampaignPlacement) -> None:
        super().__init__(f"campaign is hosted by node {placement.node_id}")
        self.placement = placement


class CampaignAuthority(Protocol):
    async def create_campaign(
        self, seed: int, *, campaign_id: str | None = None
    ) -> WorldState: ...

    async def execute(self, campaign_id: str, command: Command) -> list[Event]: ...

    async def state(self, campaign_id: str) -> WorldState: ...

    async def events(self, campaign_id: str, *, after_sequence: int = 0) -> list[Event]: ...


class PasswordHasher:
    """PBKDF2 password hashing kept provider-free and stdlib-only."""

    algorithm = "sha256"
    iterations = 310_000
    salt_bytes = 16

    def hash_password(self, password: str) -> tuple[str, str]:
        salt = secrets.token_bytes(self.salt_bytes)
        digest = hashlib.pbkdf2_hmac(
            self.algorithm, password.encode(), salt, self.iterations, dklen=32
        )
        return salt.hex(), digest.hex()

    def verify_password(self, password: str, salt_hex: str, digest_hex: str) -> bool:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            self.algorithm, password.encode(), salt, self.iterations, dklen=len(expected)
        )
        return hmac.compare_digest(actual, expected)


@dataclass(frozen=True, slots=True)
class HostedRateLimits:
    auth_per_minute: int = 20
    commands_per_minute: int = 60
    reads_per_minute: int = 300


_PLAYER_COMMAND_ACTOR_FIELD: dict[str, str] = {
    "move_actor": "actor_id",
    "explore_location": "actor_id",
    "search_location": "actor_id",
    "travel": "actor_id",
    "roll_check": "actor_id",
    "roll_saving_throw": "actor_id",
    "attack_target": "attacker_id",
    "apply_effect": "source_id",
    "apply_area_effect": "source_id",
    "end_turn": "actor_id",
    "use_reaction": "actor_id",
    "loot_container": "actor_id",
    "equip_item": "actor_id",
    "unequip_item": "actor_id",
    "start_dialogue": "actor_id",
    "choose_dialogue_option": "actor_id",
    "start_quest": "actor_id",
    "advance_quest": "actor_id",
    "buy_item": "actor_id",
    "sell_item": "actor_id",
    "complete_dynamic_quest": "actor_id",
    "harvest_resource": "actor_id",
}


class HostedCampaignService:
    """Authenticated/idempotent wrapper around the deterministic campaign authority."""

    def __init__(
        self,
        authority: CampaignAuthority,
        store: MultiplayerStore,
        *,
        node_id: str,
        public_url: str,
        session_ttl_seconds: int = 86_400,
        node_ttl_seconds: int = 30,
        placement_ttl_seconds: int = 45,
        heartbeat_seconds: int = 10,
        command_pending_ttl_seconds: int = 30,
        rate_limits: HostedRateLimits | None = None,
        clock: Callable[[], float] = time.time,
        password_hasher: PasswordHasher | None = None,
    ) -> None:
        self.authority = authority
        self.store = store
        self.node_id = node_id
        self.public_url = public_url.rstrip("/")
        self.session_ttl_seconds = session_ttl_seconds
        self.node_ttl_seconds = node_ttl_seconds
        self.placement_ttl_seconds = placement_ttl_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.command_pending_ttl_seconds = command_pending_ttl_seconds
        self.rate_limits = rate_limits or HostedRateLimits()
        self.clock = clock
        self.password_hasher = password_hasher or PasswordHasher()
        self._receipt_locks: defaultdict[tuple[str, str, str], asyncio.Lock] = defaultdict(
            asyncio.Lock
        )
        self._event_conditions: defaultdict[str, asyncio.Condition] = defaultdict(
            asyncio.Condition
        )
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def start(self, *, run_heartbeat: bool = True) -> None:
        await self.store.initialize()
        await self._heartbeat_once()
        if run_heartbeat and self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(), name=f"rpg-multiplayer-heartbeat:{self.node_id}"
            )

    async def close(self) -> None:
        task = self._heartbeat_task
        self._heartbeat_task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            await self._heartbeat_once()

    async def _heartbeat_once(self) -> None:
        now = self.clock()
        await self.store.register_node(
            self.node_id,
            self.public_url,
            now=now,
            ttl=self.node_ttl_seconds,
        )

    async def register_player(self, display_name: str, password: str) -> PlayerAccount:
        if len(password) < 10:
            raise AuthenticationError("password must be at least 10 characters")
        normalized_name = display_name.strip()
        if not normalized_name:
            raise AuthenticationError("display name cannot be empty")
        now = self.clock()
        salt, password_hash = await asyncio.to_thread(
            self.password_hasher.hash_password, password
        )
        return await self.store.create_player(
            str(uuid.uuid4()),
            normalized_name,
            salt,
            password_hash,
            now=now,
        )

    async def login(self, player_id: str, password: str) -> tuple[AuthPrincipal, str]:
        now = self.clock()
        decision = await self.store.consume_rate_limit(
            player_id,
            "auth",
            limit=self.rate_limits.auth_per_minute,
            window_seconds=60,
            now=now,
        )
        if not decision.allowed:
            raise RateLimitExceededError(decision)
        row = await self.store.get_player_auth(player_id)
        if row is None:
            raise AuthenticationError("invalid credentials")
        valid = await asyncio.to_thread(
            self.password_hasher.verify_password,
            password,
            str(row["password_salt"]),
            str(row["password_hash"]),
        )
        if not valid:
            raise AuthenticationError("invalid credentials")
        token = secrets.token_urlsafe(32)
        token_hash = self._token_hash(token)
        session_id = str(uuid.uuid4())
        expires_at = now + self.session_ttl_seconds
        await self.store.create_session(
            session_id,
            player_id,
            token_hash,
            expires_at=expires_at,
            now=now,
        )
        return (
            AuthPrincipal(
                player_id=player_id,
                display_name=str(row["display_name"]),
                session_id=session_id,
                expires_at=expires_at,
            ),
            token,
        )

    async def authenticate(self, token: str) -> AuthPrincipal:
        row = await self.store.resolve_session(self._token_hash(token), now=self.clock())
        if row is None:
            raise AuthenticationError("invalid or expired session")
        return AuthPrincipal(
            player_id=str(row["player_id"]),
            display_name=str(row["display_name"]),
            session_id=str(row["session_id"]),
            expires_at=float(row["expires_at"]),
        )

    async def logout(self, token: str) -> None:
        principal = await self.authenticate(token)
        await self.store.delete_session(principal.session_id)

    async def create_campaign(
        self,
        token: str,
        seed: int,
        *,
        campaign_id: str | None = None,
    ) -> tuple[WorldState, CampaignPlacement]:
        principal = await self.authenticate(token)
        resolved_campaign_id = campaign_id or str(uuid.uuid4())
        await self._heartbeat_once()
        placement = await self.store.assign_campaign(
            resolved_campaign_id,
            now=self.clock(),
            lease_ttl=self.placement_ttl_seconds,
        )
        if placement.node_id != self.node_id:
            raise CampaignRedirect(placement)
        world = await self.authority.create_campaign(seed, campaign_id=resolved_campaign_id)
        membership = CampaignMembership(
            campaign_id=world.campaign_id,
            player_id=principal.player_id,
            role=CampaignRole.OWNER,
            joined_at=self.clock(),
        )
        await self.store.set_membership(membership)
        return world, placement

    async def membership(self, token: str, campaign_id: str) -> CampaignMembership:
        principal = await self.authenticate(token)
        return await self._require_membership(campaign_id, principal.player_id)

    async def grant_membership(
        self,
        token: str,
        campaign_id: str,
        player_id: str,
        *,
        role: CampaignRole,
        controlled_actor_ids: set[str] | None = None,
        party_id: str | None = None,
    ) -> CampaignMembership:
        principal = await self.authenticate(token)
        owner = await self._require_membership(campaign_id, principal.player_id)
        if owner.role is not CampaignRole.OWNER:
            raise AuthorizationError("only campaign owners can change membership")
        await self._require_local_campaign(campaign_id)
        if await self.store.get_player_auth(player_id) is None:
            raise KeyError(player_id)
        if role is CampaignRole.OWNER and player_id != principal.player_id:
            raise AuthorizationError("owner transfer is not supported by v0.8")
        actor_ids = controlled_actor_ids or set()
        if role is CampaignRole.SPECTATOR and actor_ids:
            raise AuthorizationError("spectators cannot control actors")
        if actor_ids:
            world = await self.authority.state(campaign_id)
            unknown = actor_ids.difference(world.entities)
            if unknown:
                raise AuthorizationError(
                    f"unknown controlled actors: {', '.join(sorted(unknown))}"
                )
        if party_id is not None:
            party = await self.store.get_party(party_id)
            if party is None or party.campaign_id != campaign_id:
                raise AuthorizationError("party does not belong to this campaign")
        membership = CampaignMembership(
            campaign_id=campaign_id,
            player_id=player_id,
            role=role,
            controlled_actor_ids=actor_ids,
            party_id=party_id,
            joined_at=self.clock(),
        )
        await self.store.set_membership(membership)
        return membership

    async def create_party(
        self, token: str, campaign_id: str, name: str, *, party_id: str | None = None
    ) -> Party:
        principal = await self.authenticate(token)
        membership = await self._require_membership(campaign_id, principal.player_id)
        if membership.role is CampaignRole.SPECTATOR:
            raise AuthorizationError("spectators cannot create parties")
        await self._require_local_campaign(campaign_id)
        if membership.party_id is not None:
            raise AuthorizationError("player is already assigned to a party")
        normalized_name = name.strip()
        if not normalized_name:
            raise AuthorizationError("party name cannot be empty")
        party = Party(
            party_id=party_id or str(uuid.uuid4()),
            campaign_id=campaign_id,
            name=normalized_name,
            owner_player_id=principal.player_id,
            created_at=self.clock(),
        )
        await self.store.create_party(party)
        await self.store.set_party_member(
            PartyMember(
                party_id=party.party_id,
                player_id=principal.player_id,
                role=PartyRole.LEADER,
                joined_at=self.clock(),
            )
        )
        membership.party_id = party.party_id
        await self.store.set_membership(membership)
        return party

    async def add_party_member(
        self, token: str, party_id: str, player_id: str
    ) -> PartyMember:
        principal = await self.authenticate(token)
        party = await self.store.get_party(party_id)
        if party is None:
            raise KeyError(party_id)
        if party.owner_player_id != principal.player_id:
            raise AuthorizationError("only the party leader can add party members")
        await self._require_local_campaign(party.campaign_id)
        membership = await self._require_membership(party.campaign_id, player_id)
        if membership.role is CampaignRole.SPECTATOR:
            raise AuthorizationError("spectators cannot join a player party")
        if membership.party_id is not None and membership.party_id != party_id:
            raise AuthorizationError("player is already assigned to another party")
        member = PartyMember(
            party_id=party_id,
            player_id=player_id,
            role=PartyRole.MEMBER,
            joined_at=self.clock(),
        )
        await self.store.set_party_member(member)
        membership.party_id = party_id
        await self.store.set_membership(membership)
        return member

    async def placement(self, token: str, campaign_id: str) -> CampaignPlacement:
        principal = await self.authenticate(token)
        await self._require_membership(campaign_id, principal.player_id)
        return await self._campaign_placement(campaign_id)

    async def execute(
        self,
        token: str,
        campaign_id: str,
        envelope: MultiplayerCommandEnvelope,
    ) -> MultiplayerCommandResult:
        principal = await self.authenticate(token)
        membership = await self._require_membership(campaign_id, principal.player_id)
        if membership.role is CampaignRole.SPECTATOR:
            raise AuthorizationError("spectators cannot issue commands")
        self._authorize_command(membership, envelope.command)
        await self._consume_rate_limit(
            principal.player_id,
            campaign_id,
            "commands",
            self.rate_limits.commands_per_minute,
        )
        await self._require_local_campaign(campaign_id)

        key = (campaign_id, principal.player_id, envelope.client_command_id)
        async with self._receipt_locks[key]:
            command_hash = self._command_hash(envelope.command)
            claim = await self.store.claim_command(
                campaign_id,
                principal.player_id,
                envelope.client_command_id,
                command_hash,
                now=self.clock(),
                pending_ttl=self.command_pending_ttl_seconds,
            )
            if claim.state == "conflict":
                raise IdempotencyConflictError(
                    "client_command_id was already used for a different command"
                )
            if claim.state == "pending":
                raise CommandInProgressError("command with this client ID is still in progress")
            if claim.state == "replay":
                assert claim.receipt is not None
                return self._replay_receipt(claim.receipt)
            assert claim.execution_token is not None

            try:
                events = await self.authority.execute(campaign_id, envelope.command)
            except Exception as exc:
                await self.store.fail_command(
                    campaign_id,
                    principal.player_id,
                    envelope.client_command_id,
                    claim.execution_token,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    now=self.clock(),
                )
                raise

            event_payloads = [event.model_dump(mode="json") for event in events]
            first_sequence = events[0].sequence if events else None
            last_sequence = events[-1].sequence if events else None
            stored = await self.store.complete_command(
                campaign_id,
                principal.player_id,
                envelope.client_command_id,
                claim.execution_token,
                events=event_payloads,
                first_sequence=first_sequence,
                last_sequence=last_sequence,
                now=self.clock(),
            )
            if not stored:
                raise MultiplayerError("command receipt lease was lost before commit")
            async with self._event_conditions[campaign_id]:
                self._event_conditions[campaign_id].notify_all()
            return MultiplayerCommandResult(
                client_command_id=envelope.client_command_id,
                replayed=False,
                first_sequence=first_sequence,
                last_sequence=last_sequence,
                events=event_payloads,
            )

    async def receipt(
        self, token: str, campaign_id: str, client_command_id: str
    ) -> CommandReceipt | None:
        principal = await self.authenticate(token)
        await self._require_membership(campaign_id, principal.player_id)
        return await self.store.get_command_receipt(
            campaign_id, principal.player_id, client_command_id
        )

    async def state(self, token: str, campaign_id: str) -> WorldState:
        principal = await self.authenticate(token)
        membership = await self._require_membership(campaign_id, principal.player_id)
        if membership.role not in {CampaignRole.OWNER, CampaignRole.SPECTATOR}:
            raise AuthorizationError("raw authoritative state is owner/spectator-only")
        await self._consume_rate_limit(
            principal.player_id,
            campaign_id,
            "reads",
            self.rate_limits.reads_per_minute,
        )
        await self._require_local_campaign(campaign_id)
        return await self.authority.state(campaign_id)

    async def events(
        self,
        token: str,
        campaign_id: str,
        *,
        after_sequence: int = 0,
    ) -> list[Event]:
        principal = await self.authenticate(token)
        membership = await self._require_membership(campaign_id, principal.player_id)
        await self._consume_rate_limit(
            principal.player_id,
            campaign_id,
            "reads",
            self.rate_limits.reads_per_minute,
        )
        await self._require_local_campaign(campaign_id)
        events = await self.authority.events(campaign_id, after_sequence=after_sequence)
        return self._filter_events(membership, events)

    async def event_batch(
        self,
        token: str,
        campaign_id: str,
        *,
        after_sequence: int = 0,
    ) -> EventStreamEnvelope:
        principal = await self.authenticate(token)
        membership = await self._require_membership(campaign_id, principal.player_id)
        await self._consume_rate_limit(
            principal.player_id,
            campaign_id,
            "reads",
            self.rate_limits.reads_per_minute,
        )
        await self._require_local_campaign(campaign_id)
        raw = await self.authority.events(campaign_id, after_sequence=after_sequence)
        cursor = raw[-1].sequence if raw else after_sequence
        visible = self._filter_events(membership, raw)
        return EventStreamEnvelope(
            kind="events",
            cursor=cursor,
            events=[event.model_dump(mode="json") for event in visible],
        )

    async def stream_events(
        self,
        token: str,
        campaign_id: str,
        *,
        after_sequence: int = 0,
        heartbeat_seconds: float = 15.0,
    ) -> AsyncIterator[EventStreamEnvelope]:
        principal = await self.authenticate(token)
        membership = await self._require_membership(campaign_id, principal.player_id)
        await self._require_local_campaign(campaign_id)
        cursor = after_sequence
        condition = self._event_conditions[campaign_id]
        while True:
            events = await self.authority.events(campaign_id, after_sequence=cursor)
            if events:
                cursor = events[-1].sequence
                visible = self._filter_events(membership, events)
                if visible:
                    yield EventStreamEnvelope(
                        kind="events",
                        cursor=cursor,
                        events=[event.model_dump(mode="json") for event in visible],
                    )
                    continue
            try:
                async with asyncio.timeout(heartbeat_seconds):
                    async with condition:
                        await condition.wait()
            except TimeoutError:
                yield EventStreamEnvelope(kind="heartbeat", cursor=cursor)

    async def _require_membership(
        self, campaign_id: str, player_id: str
    ) -> CampaignMembership:
        membership = await self.store.get_membership(campaign_id, player_id)
        if membership is None:
            raise AuthorizationError("player is not a member of this campaign")
        return membership

    async def _campaign_placement(self, campaign_id: str) -> CampaignPlacement:
        await self._heartbeat_once()
        placement = await self.store.assign_campaign(
            campaign_id,
            now=self.clock(),
            lease_ttl=self.placement_ttl_seconds,
        )
        if placement.node_id == self.node_id:
            renewed = await self.store.renew_campaign_placement(
                campaign_id,
                self.node_id,
                now=self.clock(),
                lease_ttl=self.placement_ttl_seconds,
            )
            if renewed is not None:
                return renewed
        return placement

    async def _require_local_campaign(self, campaign_id: str) -> CampaignPlacement:
        placement = await self._campaign_placement(campaign_id)
        if placement.node_id != self.node_id:
            raise CampaignRedirect(placement)
        return placement

    async def _consume_rate_limit(
        self,
        player_id: str,
        campaign_id: str,
        bucket: str,
        limit: int,
    ) -> None:
        decision = await self.store.consume_rate_limit(
            f"{player_id}:{campaign_id}",
            bucket,
            limit=limit,
            window_seconds=60,
            now=self.clock(),
        )
        if not decision.allowed:
            raise RateLimitExceededError(decision)

    def _authorize_command(
        self, membership: CampaignMembership, command: Command
    ) -> None:
        if membership.role is CampaignRole.OWNER:
            return
        field = _PLAYER_COMMAND_ACTOR_FIELD.get(command.type)
        if field is None:
            raise AuthorizationError(f"command {command.type!r} requires campaign owner role")
        actor_id = getattr(command, field)
        if actor_id is None:
            raise AuthorizationError(
                f"command {command.type!r} requires an authoritative source actor"
            )
        if actor_id not in membership.controlled_actor_ids:
            raise AuthorizationError(f"player does not control actor {actor_id!r}")

    def _filter_events(
        self, membership: CampaignMembership, events: list[Event]
    ) -> list[Event]:
        if membership.role in {CampaignRole.OWNER, CampaignRole.SPECTATOR}:
            return events
        controlled = membership.controlled_actor_ids
        public_types = {
            "time_advanced",
            "timeline_advanced",
            "calendar_advanced",
            "weather_changed",
            "timeline_pause_changed",
        }
        visible: list[Event] = []
        for event in events:
            if event.type in public_types:
                visible.append(event)
                continue
            payload = event.model_dump(mode="json")
            if any(self._payload_contains(payload, actor_id) for actor_id in controlled):
                visible.append(event)
        return visible

    @classmethod
    def _payload_contains(cls, value: object, needle: str) -> bool:
        if isinstance(value, str):
            return value == needle
        if isinstance(value, dict):
            return any(cls._payload_contains(item, needle) for item in value.values())
        if isinstance(value, list):
            return any(cls._payload_contains(item, needle) for item in value)
        return False

    def _replay_receipt(self, receipt: CommandReceipt) -> MultiplayerCommandResult:
        if receipt.status is CommandReceiptStatus.FAILED:
            detail = receipt.error_message or "previous command failed"
            raise ReplayedCommandError(detail)
        return MultiplayerCommandResult(
            client_command_id=receipt.client_command_id,
            replayed=True,
            first_sequence=receipt.first_sequence,
            last_sequence=receipt.last_sequence,
            events=receipt.events,
        )

    @staticmethod
    def deserialize_events(payloads: list[dict[str, object]]) -> list[Event]:
        return [parse_event(payload) for payload in payloads]

    @staticmethod
    def _command_hash(command: Command) -> str:
        payload = json.dumps(
            command.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()
