"""SQLite-backed hosted multiplayer identity, idempotency, rate limit, and placement state."""

from __future__ import annotations

import asyncio
import json
import secrets
import sqlite3
from pathlib import Path

from rpg_engine.multiplayer_models import (
    CampaignMembership,
    CampaignPlacement,
    CampaignRole,
    CommandClaim,
    CommandReceipt,
    CommandReceiptStatus,
    NodeRegistration,
    Party,
    PartyMember,
    PartyRole,
    PlayerAccount,
    RateLimitDecision,
)

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS multiplayer_players (
    player_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS multiplayer_sessions (
    session_id TEXT PRIMARY KEY,
    player_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at REAL NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_multiplayer_sessions_token
ON multiplayer_sessions(token_hash);
CREATE TABLE IF NOT EXISTS multiplayer_memberships (
    campaign_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    role TEXT NOT NULL,
    controlled_actor_ids TEXT NOT NULL,
    party_id TEXT,
    joined_at REAL NOT NULL,
    PRIMARY KEY (campaign_id, player_id)
);
CREATE TABLE IF NOT EXISTS multiplayer_parties (
    party_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    name TEXT NOT NULL,
    owner_player_id TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS multiplayer_party_members (
    party_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    role TEXT NOT NULL,
    joined_at REAL NOT NULL,
    PRIMARY KEY (party_id, player_id)
);
CREATE TABLE IF NOT EXISTS multiplayer_command_receipts (
    campaign_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    client_command_id TEXT NOT NULL,
    command_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    execution_token TEXT,
    pending_until REAL,
    first_sequence INTEGER,
    last_sequence INTEGER,
    events_json TEXT NOT NULL,
    error_type TEXT,
    error_message TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (campaign_id, player_id, client_command_id)
);
CREATE TABLE IF NOT EXISTS multiplayer_rate_limits (
    subject_key TEXT NOT NULL,
    bucket TEXT NOT NULL,
    window_start REAL NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (subject_key, bucket)
);
CREATE TABLE IF NOT EXISTS multiplayer_nodes (
    node_id TEXT PRIMARY KEY,
    public_url TEXT NOT NULL,
    last_seen_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS multiplayer_campaign_placements (
    campaign_id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL,
    lease_until REAL NOT NULL,
    epoch INTEGER NOT NULL
);
"""


class MultiplayerStore:
    """Thread-offloaded SQLite store so hosted coordination never blocks the event loop."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        return db

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        with self._connect() as db:
            db.executescript(_SCHEMA)

    async def create_player(
        self,
        player_id: str,
        display_name: str,
        password_salt: str,
        password_hash: str,
        *,
        now: float,
    ) -> PlayerAccount:
        return await asyncio.to_thread(
            self._create_player_sync,
            player_id,
            display_name,
            password_salt,
            password_hash,
            now,
        )

    def _create_player_sync(
        self,
        player_id: str,
        display_name: str,
        password_salt: str,
        password_hash: str,
        now: float,
    ) -> PlayerAccount:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO multiplayer_players(
                    player_id, display_name, password_salt, password_hash, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (player_id, display_name, password_salt, password_hash, now),
            )
        return PlayerAccount(player_id=player_id, display_name=display_name, created_at=now)

    async def get_player_auth(self, player_id: str) -> sqlite3.Row | None:
        return await asyncio.to_thread(self._get_player_auth_sync, player_id)

    def _get_player_auth_sync(self, player_id: str) -> sqlite3.Row | None:
        with self._connect() as db:
            return db.execute(
                """
                SELECT player_id, display_name, password_salt, password_hash, created_at
                FROM multiplayer_players WHERE player_id = ?
                """,
                (player_id,),
            ).fetchone()

    async def create_session(
        self,
        session_id: str,
        player_id: str,
        token_hash: str,
        *,
        expires_at: float,
        now: float,
    ) -> None:
        await asyncio.to_thread(
            self._create_session_sync,
            session_id,
            player_id,
            token_hash,
            expires_at,
            now,
        )

    def _create_session_sync(
        self,
        session_id: str,
        player_id: str,
        token_hash: str,
        expires_at: float,
        now: float,
    ) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO multiplayer_sessions(
                    session_id, player_id, token_hash, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, player_id, token_hash, expires_at, now),
            )

    async def resolve_session(self, token_hash: str, *, now: float) -> sqlite3.Row | None:
        return await asyncio.to_thread(self._resolve_session_sync, token_hash, now)

    def _resolve_session_sync(self, token_hash: str, now: float) -> sqlite3.Row | None:
        with self._connect() as db:
            db.execute("DELETE FROM multiplayer_sessions WHERE expires_at <= ?", (now,))
            return db.execute(
                """
                SELECT s.session_id, s.player_id, s.expires_at, p.display_name
                FROM multiplayer_sessions AS s
                JOIN multiplayer_players AS p ON p.player_id = s.player_id
                WHERE s.token_hash = ? AND s.expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()

    async def delete_session(self, session_id: str) -> None:
        await asyncio.to_thread(self._delete_session_sync, session_id)

    def _delete_session_sync(self, session_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM multiplayer_sessions WHERE session_id = ?", (session_id,))

    async def set_membership(self, membership: CampaignMembership) -> None:
        await asyncio.to_thread(self._set_membership_sync, membership)

    def _set_membership_sync(self, membership: CampaignMembership) -> None:
        actor_json = json.dumps(sorted(membership.controlled_actor_ids))
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO multiplayer_memberships(
                    campaign_id, player_id, role, controlled_actor_ids, party_id, joined_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(campaign_id, player_id) DO UPDATE SET
                    role = excluded.role,
                    controlled_actor_ids = excluded.controlled_actor_ids,
                    party_id = excluded.party_id
                """,
                (
                    membership.campaign_id,
                    membership.player_id,
                    membership.role.value,
                    actor_json,
                    membership.party_id,
                    membership.joined_at,
                ),
            )

    async def get_membership(
        self, campaign_id: str, player_id: str
    ) -> CampaignMembership | None:
        return await asyncio.to_thread(self._get_membership_sync, campaign_id, player_id)

    def _get_membership_sync(
        self, campaign_id: str, player_id: str
    ) -> CampaignMembership | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT campaign_id, player_id, role, controlled_actor_ids, party_id, joined_at
                FROM multiplayer_memberships
                WHERE campaign_id = ? AND player_id = ?
                """,
                (campaign_id, player_id),
            ).fetchone()
        if row is None:
            return None
        return CampaignMembership(
            campaign_id=str(row["campaign_id"]),
            player_id=str(row["player_id"]),
            role=CampaignRole(str(row["role"])),
            controlled_actor_ids=set(json.loads(str(row["controlled_actor_ids"]))),
            party_id=str(row["party_id"]) if row["party_id"] is not None else None,
            joined_at=float(row["joined_at"]),
        )

    async def create_party(self, party: Party) -> None:
        await asyncio.to_thread(self._create_party_sync, party)

    def _create_party_sync(self, party: Party) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO multiplayer_parties(
                    party_id, campaign_id, name, owner_player_id, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    party.party_id,
                    party.campaign_id,
                    party.name,
                    party.owner_player_id,
                    party.created_at,
                ),
            )

    async def get_party(self, party_id: str) -> Party | None:
        return await asyncio.to_thread(self._get_party_sync, party_id)

    def _get_party_sync(self, party_id: str) -> Party | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT party_id, campaign_id, name, owner_player_id, created_at
                FROM multiplayer_parties WHERE party_id = ?
                """,
                (party_id,),
            ).fetchone()
        if row is None:
            return None
        return Party(
            party_id=str(row["party_id"]),
            campaign_id=str(row["campaign_id"]),
            name=str(row["name"]),
            owner_player_id=str(row["owner_player_id"]),
            created_at=float(row["created_at"]),
        )

    async def set_party_member(self, member: PartyMember) -> None:
        await asyncio.to_thread(self._set_party_member_sync, member)

    def _set_party_member_sync(self, member: PartyMember) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO multiplayer_party_members(party_id, player_id, role, joined_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(party_id, player_id) DO UPDATE SET role = excluded.role
                """,
                (member.party_id, member.player_id, member.role.value, member.joined_at),
            )

    async def list_party_members(self, party_id: str) -> list[PartyMember]:
        return await asyncio.to_thread(self._list_party_members_sync, party_id)

    def _list_party_members_sync(self, party_id: str) -> list[PartyMember]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT party_id, player_id, role, joined_at
                FROM multiplayer_party_members WHERE party_id = ?
                ORDER BY player_id
                """,
                (party_id,),
            ).fetchall()
        return [
            PartyMember(
                party_id=str(row["party_id"]),
                player_id=str(row["player_id"]),
                role=PartyRole(str(row["role"])),
                joined_at=float(row["joined_at"]),
            )
            for row in rows
        ]

    async def claim_command(
        self,
        campaign_id: str,
        player_id: str,
        client_command_id: str,
        command_hash: str,
        *,
        now: float,
        pending_ttl: float,
    ) -> CommandClaim:
        return await asyncio.to_thread(
            self._claim_command_sync,
            campaign_id,
            player_id,
            client_command_id,
            command_hash,
            now,
            pending_ttl,
        )

    def _claim_command_sync(
        self,
        campaign_id: str,
        player_id: str,
        client_command_id: str,
        command_hash: str,
        now: float,
        pending_ttl: float,
    ) -> CommandClaim:
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT * FROM multiplayer_command_receipts
                WHERE campaign_id = ? AND player_id = ? AND client_command_id = ?
                """,
                (campaign_id, player_id, client_command_id),
            ).fetchone()
            token = secrets.token_urlsafe(24)
            if row is None:
                pending_until = now + pending_ttl
                db.execute(
                    """
                    INSERT INTO multiplayer_command_receipts(
                        campaign_id, player_id, client_command_id, command_hash, status,
                        execution_token, pending_until, events_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, '[]', ?, ?)
                    """,
                    (
                        campaign_id,
                        player_id,
                        client_command_id,
                        command_hash,
                        CommandReceiptStatus.PENDING.value,
                        token,
                        pending_until,
                        now,
                        now,
                    ),
                )
                db.commit()
                return CommandClaim(state="claimed", execution_token=token)

            receipt = self._receipt_from_row(row)
            if receipt.command_hash != command_hash:
                db.rollback()
                return CommandClaim(state="conflict", receipt=receipt)
            if receipt.status in {CommandReceiptStatus.COMMITTED, CommandReceiptStatus.FAILED}:
                db.rollback()
                return CommandClaim(state="replay", receipt=receipt)
            if receipt.pending_until is not None and receipt.pending_until > now:
                db.rollback()
                return CommandClaim(state="pending", receipt=receipt)

            pending_until = now + pending_ttl
            db.execute(
                """
                UPDATE multiplayer_command_receipts
                SET execution_token = ?, pending_until = ?, updated_at = ?
                WHERE campaign_id = ? AND player_id = ? AND client_command_id = ?
                """,
                (
                    token,
                    pending_until,
                    now,
                    campaign_id,
                    player_id,
                    client_command_id,
                ),
            )
            db.commit()
            return CommandClaim(state="claimed", execution_token=token)
        finally:
            db.close()

    async def complete_command(
        self,
        campaign_id: str,
        player_id: str,
        client_command_id: str,
        execution_token: str,
        *,
        events: list[dict[str, object]],
        first_sequence: int | None,
        last_sequence: int | None,
        now: float,
    ) -> bool:
        return await asyncio.to_thread(
            self._finish_command_sync,
            campaign_id,
            player_id,
            client_command_id,
            execution_token,
            CommandReceiptStatus.COMMITTED,
            events,
            first_sequence,
            last_sequence,
            None,
            None,
            now,
        )

    async def fail_command(
        self,
        campaign_id: str,
        player_id: str,
        client_command_id: str,
        execution_token: str,
        *,
        error_type: str,
        error_message: str,
        now: float,
    ) -> bool:
        return await asyncio.to_thread(
            self._finish_command_sync,
            campaign_id,
            player_id,
            client_command_id,
            execution_token,
            CommandReceiptStatus.FAILED,
            [],
            None,
            None,
            error_type,
            error_message,
            now,
        )

    def _finish_command_sync(
        self,
        campaign_id: str,
        player_id: str,
        client_command_id: str,
        execution_token: str,
        status: CommandReceiptStatus,
        events: list[dict[str, object]],
        first_sequence: int | None,
        last_sequence: int | None,
        error_type: str | None,
        error_message: str | None,
        now: float,
    ) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                """
                UPDATE multiplayer_command_receipts
                SET status = ?, execution_token = NULL, pending_until = NULL,
                    first_sequence = ?, last_sequence = ?, events_json = ?,
                    error_type = ?, error_message = ?, updated_at = ?
                WHERE campaign_id = ? AND player_id = ? AND client_command_id = ?
                    AND status = ? AND execution_token = ?
                """,
                (
                    status.value,
                    first_sequence,
                    last_sequence,
                    json.dumps(events, sort_keys=True, separators=(",", ":")),
                    error_type,
                    error_message,
                    now,
                    campaign_id,
                    player_id,
                    client_command_id,
                    CommandReceiptStatus.PENDING.value,
                    execution_token,
                ),
            )
            return cursor.rowcount == 1

    async def get_command_receipt(
        self, campaign_id: str, player_id: str, client_command_id: str
    ) -> CommandReceipt | None:
        return await asyncio.to_thread(
            self._get_command_receipt_sync, campaign_id, player_id, client_command_id
        )

    def _get_command_receipt_sync(
        self, campaign_id: str, player_id: str, client_command_id: str
    ) -> CommandReceipt | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM multiplayer_command_receipts
                WHERE campaign_id = ? AND player_id = ? AND client_command_id = ?
                """,
                (campaign_id, player_id, client_command_id),
            ).fetchone()
        return self._receipt_from_row(row) if row is not None else None

    def _receipt_from_row(self, row: sqlite3.Row) -> CommandReceipt:
        return CommandReceipt(
            campaign_id=str(row["campaign_id"]),
            player_id=str(row["player_id"]),
            client_command_id=str(row["client_command_id"]),
            command_hash=str(row["command_hash"]),
            status=CommandReceiptStatus(str(row["status"])),
            first_sequence=(
                int(row["first_sequence"]) if row["first_sequence"] is not None else None
            ),
            last_sequence=(
                int(row["last_sequence"]) if row["last_sequence"] is not None else None
            ),
            events=list(json.loads(str(row["events_json"]))),
            error_type=str(row["error_type"]) if row["error_type"] is not None else None,
            error_message=(
                str(row["error_message"]) if row["error_message"] is not None else None
            ),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            pending_until=float(row["pending_until"]) if row["pending_until"] is not None else None,
        )

    async def consume_rate_limit(
        self,
        subject_key: str,
        bucket: str,
        *,
        limit: int,
        window_seconds: int,
        now: float,
    ) -> RateLimitDecision:
        return await asyncio.to_thread(
            self._consume_rate_limit_sync,
            subject_key,
            bucket,
            limit,
            window_seconds,
            now,
        )

    def _consume_rate_limit_sync(
        self,
        subject_key: str,
        bucket: str,
        limit: int,
        window_seconds: int,
        now: float,
    ) -> RateLimitDecision:
        window_start = float(int(now // window_seconds) * window_seconds)
        reset_at = window_start + window_seconds
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT window_start, count FROM multiplayer_rate_limits
                WHERE subject_key = ? AND bucket = ?
                """,
                (subject_key, bucket),
            ).fetchone()
            count = 0
            if row is not None and float(row["window_start"]) == window_start:
                count = int(row["count"])
            if count >= limit:
                db.rollback()
                return RateLimitDecision(
                    allowed=False,
                    remaining=0,
                    retry_after_seconds=max(0.0, reset_at - now),
                    reset_at=reset_at,
                )
            count += 1
            db.execute(
                """
                INSERT INTO multiplayer_rate_limits(subject_key, bucket, window_start, count)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(subject_key, bucket) DO UPDATE SET
                    window_start = excluded.window_start,
                    count = excluded.count
                """,
                (subject_key, bucket, window_start, count),
            )
            db.commit()
            return RateLimitDecision(
                allowed=True,
                remaining=max(0, limit - count),
                retry_after_seconds=0.0,
                reset_at=reset_at,
            )
        finally:
            db.close()

    async def register_node(
        self,
        node_id: str,
        public_url: str,
        *,
        now: float,
        ttl: float,
    ) -> NodeRegistration:
        return await asyncio.to_thread(
            self._register_node_sync, node_id, public_url, now, ttl
        )

    def _register_node_sync(
        self, node_id: str, public_url: str, now: float, ttl: float
    ) -> NodeRegistration:
        expires_at = now + ttl
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO multiplayer_nodes(node_id, public_url, last_seen_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    public_url = excluded.public_url,
                    last_seen_at = excluded.last_seen_at,
                    expires_at = excluded.expires_at
                """,
                (node_id, public_url, now, expires_at),
            )
        return NodeRegistration(
            node_id=node_id,
            public_url=public_url,
            last_seen_at=now,
            expires_at=expires_at,
        )

    async def live_nodes(self, *, now: float) -> list[NodeRegistration]:
        return await asyncio.to_thread(self._live_nodes_sync, now)

    def _live_nodes_sync(self, now: float) -> list[NodeRegistration]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT node_id, public_url, last_seen_at, expires_at
                FROM multiplayer_nodes
                WHERE expires_at > ?
                ORDER BY node_id
                """,
                (now,),
            ).fetchall()
        return [
            NodeRegistration(
                node_id=str(row["node_id"]),
                public_url=str(row["public_url"]),
                last_seen_at=float(row["last_seen_at"]),
                expires_at=float(row["expires_at"]),
            )
            for row in rows
        ]

    async def assign_campaign(
        self,
        campaign_id: str,
        *,
        now: float,
        lease_ttl: float,
    ) -> CampaignPlacement:
        return await asyncio.to_thread(
            self._assign_campaign_sync, campaign_id, now, lease_ttl
        )

    def _assign_campaign_sync(
        self, campaign_id: str, now: float, lease_ttl: float
    ) -> CampaignPlacement:
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                """
                SELECT p.campaign_id, p.node_id, p.lease_until, p.epoch, n.public_url,
                       n.expires_at
                FROM multiplayer_campaign_placements AS p
                LEFT JOIN multiplayer_nodes AS n ON n.node_id = p.node_id
                WHERE p.campaign_id = ?
                """,
                (campaign_id,),
            ).fetchone()
            if (
                existing is not None
                and existing["public_url"] is not None
                and float(existing["lease_until"]) > now
                and float(existing["expires_at"]) > now
            ):
                db.rollback()
                return CampaignPlacement(
                    campaign_id=campaign_id,
                    node_id=str(existing["node_id"]),
                    public_url=str(existing["public_url"]),
                    lease_until=float(existing["lease_until"]),
                    epoch=int(existing["epoch"]),
                )

            nodes = db.execute(
                """
                SELECT node_id, public_url FROM multiplayer_nodes
                WHERE expires_at > ? ORDER BY node_id
                """,
                (now,),
            ).fetchall()
            if not nodes:
                raise RuntimeError("no live multiplayer nodes")
            chosen = max(
                nodes,
                key=lambda row: self.rendezvous_score(campaign_id, str(row["node_id"])),
            )
            epoch = int(existing["epoch"]) + 1 if existing is not None else 1
            lease_until = now + lease_ttl
            db.execute(
                """
                INSERT INTO multiplayer_campaign_placements(
                    campaign_id, node_id, lease_until, epoch
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(campaign_id) DO UPDATE SET
                    node_id = excluded.node_id,
                    lease_until = excluded.lease_until,
                    epoch = excluded.epoch
                """,
                (campaign_id, str(chosen["node_id"]), lease_until, epoch),
            )
            db.commit()
            return CampaignPlacement(
                campaign_id=campaign_id,
                node_id=str(chosen["node_id"]),
                public_url=str(chosen["public_url"]),
                lease_until=lease_until,
                epoch=epoch,
            )
        finally:
            db.close()

    async def renew_campaign_placement(
        self,
        campaign_id: str,
        node_id: str,
        *,
        now: float,
        lease_ttl: float,
    ) -> CampaignPlacement | None:
        return await asyncio.to_thread(
            self._renew_campaign_placement_sync,
            campaign_id,
            node_id,
            now,
            lease_ttl,
        )

    def _renew_campaign_placement_sync(
        self,
        campaign_id: str,
        node_id: str,
        now: float,
        lease_ttl: float,
    ) -> CampaignPlacement | None:
        lease_until = now + lease_ttl
        with self._connect() as db:
            cursor = db.execute(
                """
                UPDATE multiplayer_campaign_placements
                SET lease_until = ?
                WHERE campaign_id = ? AND node_id = ?
                """,
                (lease_until, campaign_id, node_id),
            )
            if cursor.rowcount != 1:
                return None
            row = db.execute(
                """
                SELECT p.epoch, n.public_url FROM multiplayer_campaign_placements AS p
                JOIN multiplayer_nodes AS n ON n.node_id = p.node_id
                WHERE p.campaign_id = ? AND p.node_id = ?
                """,
                (campaign_id, node_id),
            ).fetchone()
        if row is None:
            return None
        return CampaignPlacement(
            campaign_id=campaign_id,
            node_id=node_id,
            public_url=str(row["public_url"]),
            lease_until=lease_until,
            epoch=int(row["epoch"]),
        )

    @staticmethod
    def rendezvous_score(campaign_id: str, node_id: str) -> int:
        import hashlib

        digest = hashlib.blake2b(
            f"{campaign_id}\0{node_id}".encode(), digest_size=16, person=b"rpg-place-v08"
        ).digest()
        return int.from_bytes(digest, "big")
