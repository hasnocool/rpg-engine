"""Async SQLite event store and snapshot persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from rpg_engine.events import Event, parse_event
from rpg_engine.models import WorldState

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id TEXT PRIMARY KEY,
    seed INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    campaign_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (campaign_id, sequence),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS snapshots (
    campaign_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (campaign_id, sequence),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_events_campaign_sequence
ON events(campaign_id, sequence);
"""


class SQLiteEventStore:
    """Non-blocking persistence using aiosqlite and WAL mode."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()

    async def create_campaign(self, campaign_id: str, seed: int) -> None:
        created_at = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO campaigns(campaign_id, seed, created_at) VALUES (?, ?, ?)",
                (campaign_id, seed, created_at),
            )
            await db.commit()

    async def get_seed(self, campaign_id: str) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT seed FROM campaigns WHERE campaign_id = ?", (campaign_id,)
            )
            row = await cursor.fetchone()
        if row is None:
            raise KeyError(campaign_id)
        return int(row[0])

    async def append_events(self, campaign_id: str, events: list[Event]) -> None:
        if not events:
            return
        created_at = datetime.now(UTC).isoformat()
        rows = [
            (
                campaign_id,
                event.sequence,
                event.type,
                event.model_dump_json(),
                created_at,
            )
            for event in events
        ]
        async with aiosqlite.connect(self.path) as db:
            await db.executemany(
                """
                INSERT INTO events(campaign_id, sequence, event_type, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
            await db.commit()

    async def list_events(self, campaign_id: str, *, after_sequence: int = 0) -> list[Event]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """
                SELECT payload FROM events
                WHERE campaign_id = ? AND sequence > ?
                ORDER BY sequence ASC
                """,
                (campaign_id, after_sequence),
            )
            rows = await cursor.fetchall()
        return [parse_event(json.loads(str(row[0]))) for row in rows]

    async def save_snapshot(self, world: WorldState) -> None:
        created_at = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO snapshots(campaign_id, sequence, payload, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (world.campaign_id, world.sequence, world.model_dump_json(), created_at),
            )
            await db.commit()

    async def load_latest_snapshot(self, campaign_id: str) -> WorldState | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """
                SELECT payload FROM snapshots
                WHERE campaign_id = ?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (campaign_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return WorldState.model_validate_json(str(row[0]))
