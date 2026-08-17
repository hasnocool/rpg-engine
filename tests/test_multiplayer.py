"""v0.8 hosted multiplayer authority, idempotency, and placement tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from rpg_engine.commands import Command, MoveActorCommand
from rpg_engine.events import ActorMovedEvent, Event, TimeAdvancedEvent
from rpg_engine.models import Entity, Identity, Position, WorldState
from rpg_engine.multiplayer import (
    AuthorizationError,
    HostedCampaignService,
    HostedRateLimits,
    IdempotencyConflictError,
    PasswordHasher,
    RateLimitExceededError,
)
from rpg_engine.multiplayer_models import (
    CampaignMembership,
    CampaignRole,
    MultiplayerCommandEnvelope,
)
from rpg_engine.multiplayer_store import MultiplayerStore


class FastPasswordHasher(PasswordHasher):
    iterations = 1_000


class FakeAuthority:
    def __init__(self) -> None:
        self.worlds: dict[str, WorldState] = {}
        self.logs: dict[str, list[Event]] = {}
        self.execute_count = 0

    async def create_campaign(
        self, seed: int, *, campaign_id: str | None = None
    ) -> WorldState:
        campaign_id = campaign_id or "generated"
        world = WorldState(campaign_id=campaign_id, seed=seed)
        world.entities["hero"] = Entity(id="hero", identity=Identity(name="Hero"))
        world.entities["villain"] = Entity(id="villain", identity=Identity(name="Villain"))
        self.worlds[campaign_id] = world
        self.logs[campaign_id] = []
        return world.model_copy(deep=True)

    async def execute(self, campaign_id: str, command: Command) -> list[Event]:
        self.execute_count += 1
        world = self.worlds[campaign_id]
        world.sequence += 1
        actor_id = str(command.model_dump().get("actor_id", "hero"))
        event = ActorMovedEvent(
            campaign_id=campaign_id,
            sequence=world.sequence,
            actor_id=actor_id,
            position=Position(area="village"),
        )
        self.logs[campaign_id].append(event)
        return [event]

    async def state(self, campaign_id: str) -> WorldState:
        return self.worlds[campaign_id].model_copy(deep=True)

    async def events(self, campaign_id: str, *, after_sequence: int = 0) -> list[Event]:
        return [event for event in self.logs[campaign_id] if event.sequence > after_sequence]


def test_password_hasher_round_trip() -> None:
    hasher = FastPasswordHasher()
    salt, digest = hasher.hash_password("correct horse battery staple")
    assert hasher.verify_password("correct horse battery staple", salt, digest)
    assert not hasher.verify_password("wrong password", salt, digest)


@pytest.mark.asyncio
async def test_store_sessions_memberships_and_parties(tmp_path: Path) -> None:
    store = MultiplayerStore(tmp_path / "multiplayer.db")
    await store.initialize()
    account = await store.create_player("p1", "Player One", "aa", "bb", now=10.0)
    assert account.player_id == "p1"
    await store.create_session("s1", "p1", "tokenhash", expires_at=100.0, now=10.0)
    session = await store.resolve_session("tokenhash", now=20.0)
    assert session is not None
    assert session["player_id"] == "p1"
    assert await store.resolve_session("tokenhash", now=101.0) is None

    membership = CampaignMembership(
        campaign_id="c1",
        player_id="p1",
        role=CampaignRole.PLAYER,
        controlled_actor_ids={"hero"},
        joined_at=10.0,
    )
    await store.set_membership(membership)
    loaded = await store.get_membership("c1", "p1")
    assert loaded == membership


@pytest.mark.asyncio
async def test_idempotency_receipt_takeover_is_fenced(tmp_path: Path) -> None:
    store = MultiplayerStore(tmp_path / "receipts.db")
    await store.initialize()
    first = await store.claim_command(
        "c1", "p1", "cmd-1", "hash-a", now=0.0, pending_ttl=10.0
    )
    assert first.state == "claimed"
    assert first.execution_token is not None

    pending = await store.claim_command(
        "c1", "p1", "cmd-1", "hash-a", now=5.0, pending_ttl=10.0
    )
    assert pending.state == "pending"

    takeover = await store.claim_command(
        "c1", "p1", "cmd-1", "hash-a", now=11.0, pending_ttl=10.0
    )
    assert takeover.state == "claimed"
    assert takeover.execution_token is not None
    assert takeover.execution_token != first.execution_token

    stale_commit = await store.complete_command(
        "c1",
        "p1",
        "cmd-1",
        first.execution_token,
        events=[],
        first_sequence=None,
        last_sequence=None,
        now=12.0,
    )
    assert not stale_commit
    current_commit = await store.complete_command(
        "c1",
        "p1",
        "cmd-1",
        takeover.execution_token,
        events=[],
        first_sequence=None,
        last_sequence=None,
        now=12.0,
    )
    assert current_commit

    replay = await store.claim_command(
        "c1", "p1", "cmd-1", "hash-a", now=13.0, pending_ttl=10.0
    )
    assert replay.state == "replay"
    conflict = await store.claim_command(
        "c1", "p1", "cmd-1", "hash-b", now=13.0, pending_ttl=10.0
    )
    assert conflict.state == "conflict"


@pytest.mark.asyncio
async def test_database_backed_rate_limit(tmp_path: Path) -> None:
    store = MultiplayerStore(tmp_path / "rate.db")
    await store.initialize()
    first = await store.consume_rate_limit(
        "player", "commands", limit=2, window_seconds=60, now=1.0
    )
    second = await store.consume_rate_limit(
        "player", "commands", limit=2, window_seconds=60, now=2.0
    )
    denied = await store.consume_rate_limit(
        "player", "commands", limit=2, window_seconds=60, now=3.0
    )
    reset = await store.consume_rate_limit(
        "player", "commands", limit=2, window_seconds=60, now=61.0
    )
    assert first.allowed and second.allowed
    assert not denied.allowed
    assert denied.retry_after_seconds == 57.0
    assert reset.allowed


@pytest.mark.asyncio
async def test_horizontal_placement_is_deterministic_and_fails_over(tmp_path: Path) -> None:
    store = MultiplayerStore(tmp_path / "placement.db")
    await store.initialize()
    await store.register_node("node-a", "https://a.example", now=0.0, ttl=10.0)
    await store.register_node("node-b", "https://b.example", now=0.0, ttl=10.0)
    placement = await store.assign_campaign("campaign", now=1.0, lease_ttl=30.0)
    expected = max(
        ["node-a", "node-b"],
        key=lambda node: store.rendezvous_score("campaign", node),
    )
    assert placement.node_id == expected

    survivor = "node-b" if expected == "node-a" else "node-a"
    await store.register_node(survivor, f"https://{survivor}.example", now=11.0, ttl=10.0)
    failed_over = await store.assign_campaign("campaign", now=12.0, lease_ttl=30.0)
    assert failed_over.node_id == survivor
    assert failed_over.epoch == placement.epoch + 1


@pytest.mark.asyncio
async def test_hosted_service_auth_roles_idempotency_and_event_filtering(tmp_path: Path) -> None:
    now = 1_000.0

    def clock() -> float:
        return now

    authority = FakeAuthority()
    store = MultiplayerStore(tmp_path / "hosted.db")
    service = HostedCampaignService(
        authority,
        store,
        node_id="node-1",
        public_url="https://node-1.example",
        rate_limits=HostedRateLimits(auth_per_minute=20, commands_per_minute=10),
        clock=clock,
        password_hasher=FastPasswordHasher(),
    )
    await service.start(run_heartbeat=False)
    try:
        owner = await service.register_player("Owner", "owner-password-123")
        owner_principal, owner_token = await service.login(owner.player_id, "owner-password-123")
        assert owner_principal.player_id == owner.player_id
        world, placement = await service.create_campaign(owner_token, 123, campaign_id="c1")
        assert world.campaign_id == "c1"
        assert placement.node_id == "node-1"

        player = await service.register_player("Player", "player-password-123")
        _, player_token = await service.login(player.player_id, "player-password-123")
        await service.grant_membership(
            owner_token,
            "c1",
            player.player_id,
            role=CampaignRole.PLAYER,
            controlled_actor_ids={"hero"},
        )
        party = await service.create_party(owner_token, "c1", "North Road Party")
        party_member = await service.add_party_member(owner_token, party.party_id, player.player_id)
        assert party_member.player_id == player.player_id
        assert (await service.membership(player_token, "c1")).party_id == party.party_id

        envelope = MultiplayerCommandEnvelope(
            client_command_id="optimistic-1",
            command=MoveActorCommand(actor_id="hero", position=Position(area="village")),
        )
        first = await service.execute(player_token, "c1", envelope)
        second = await service.execute(player_token, "c1", envelope)
        assert not first.replayed
        assert second.replayed
        assert authority.execute_count == 1

        with pytest.raises(IdempotencyConflictError):
            await service.execute(
                player_token,
                "c1",
                MultiplayerCommandEnvelope(
                    client_command_id="optimistic-1",
                    command=MoveActorCommand(
                        actor_id="hero", position=Position(area="forest")
                    ),
                ),
            )

        with pytest.raises(AuthorizationError):
            await service.execute(
                player_token,
                "c1",
                MultiplayerCommandEnvelope(
                    client_command_id="optimistic-2",
                    command=MoveActorCommand(
                        actor_id="villain", position=Position(area="village")
                    ),
                ),
            )

        spectator = await service.register_player("Watcher", "watcher-password-123")
        _, spectator_token = await service.login(spectator.player_id, "watcher-password-123")
        await service.grant_membership(
            owner_token, "c1", spectator.player_id, role=CampaignRole.SPECTATOR
        )
        with pytest.raises(AuthorizationError):
            await service.execute(
                spectator_token,
                "c1",
                MultiplayerCommandEnvelope(
                    client_command_id="spectator-write",
                    command=MoveActorCommand(
                        actor_id="hero", position=Position(area="village")
                    ),
                ),
            )

        authority.logs["c1"] = [
            ActorMovedEvent(
                sequence=1,
                campaign_id="c1",
                actor_id="hero",
                position=Position(area="village"),
            ),
            ActorMovedEvent(
                sequence=2,
                campaign_id="c1",
                actor_id="villain",
                position=Position(area="forest"),
            ),
            TimeAdvancedEvent(
                sequence=3, campaign_id="c1", minutes=5, time_minutes=5
            ),
        ]
        player_events = await service.events(player_token, "c1")
        assert [event.sequence for event in player_events] == [1, 3]
        hidden_only_batch = await service.event_batch(player_token, "c1", after_sequence=1)
        assert hidden_only_batch.cursor == 3
        assert [event["sequence"] for event in hidden_only_batch.events] == [3]
        spectator_events = await service.events(spectator_token, "c1")
        assert [event.sequence for event in spectator_events] == [1, 2, 3]
        assert (await service.state(spectator_token, "c1")).campaign_id == "c1"
        with pytest.raises(AuthorizationError):
            await service.state(player_token, "c1")
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_hosted_service_rate_limits_commands(tmp_path: Path) -> None:
    authority = FakeAuthority()
    store = MultiplayerStore(tmp_path / "limited.db")
    service = HostedCampaignService(
        authority,
        store,
        node_id="node-1",
        public_url="https://node-1.example",
        rate_limits=HostedRateLimits(commands_per_minute=1),
        clock=lambda: 100.0,
        password_hasher=FastPasswordHasher(),
    )
    await service.start(run_heartbeat=False)
    try:
        owner = await service.register_player("Owner", "owner-password-123")
        _, token = await service.login(owner.player_id, "owner-password-123")
        await service.create_campaign(token, 1, campaign_id="limited")
        await service.execute(
            token,
            "limited",
            MultiplayerCommandEnvelope(
                client_command_id="one",
                command=MoveActorCommand(actor_id="hero", position=Position(area="village")),
            ),
        )
        with pytest.raises(RateLimitExceededError):
            await service.execute(
                token,
                "limited",
                MultiplayerCommandEnvelope(
                    client_command_id="two",
                    command=MoveActorCommand(
                        actor_id="hero", position=Position(area="forest")
                    ),
                ),
            )
    finally:
        await service.close()
