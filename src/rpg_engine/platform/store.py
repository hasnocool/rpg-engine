"""SQLite-backed public release registry."""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from rpg_engine.platform.models import ClientRelease, ContentRelease, MarketplaceListing


class PlatformRegistryStore:
    def __init__(self, path: Path | str = "rpg_platform.db") -> None:
        self.path = str(path)

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS client_releases (
                    client_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (client_id, version, channel)
                );
                CREATE TABLE IF NOT EXISTS content_releases (
                    pack_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (pack_id, version)
                );
                CREATE TABLE IF NOT EXISTS marketplace_listings (
                    listing_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                """
            )
            await db.commit()

    async def put_client(self, release: ClientRelease) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO client_releases(client_id, version, channel, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(client_id, version, channel)
                DO UPDATE SET payload=excluded.payload
                """,
                (release.client_id, release.version, release.channel, release.model_dump_json()),
            )
            await db.commit()

    async def clients(
        self,
        *,
        client_id: str | None = None,
        channel: str | None = None,
    ) -> list[ClientRelease]:
        clauses: list[str] = []
        params: list[str] = []
        if client_id is not None:
            clauses.append("client_id = ?")
            params.append(client_id)
        if channel is not None:
            clauses.append("channel = ?")
            params.append(channel)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(f"SELECT payload FROM client_releases{where}", params)
            rows = await cursor.fetchall()
        return [ClientRelease.model_validate(json.loads(row[0])) for row in rows]

    async def put_content(self, release: ContentRelease) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO content_releases(pack_id, version, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(pack_id, version)
                DO UPDATE SET payload=excluded.payload
                """,
                (release.pack_id, release.version, release.model_dump_json()),
            )
            await db.commit()

    async def content(self, *, pack_id: str | None = None) -> list[ContentRelease]:
        query = "SELECT payload FROM content_releases"
        params: tuple[str, ...] = ()
        if pack_id is not None:
            query += " WHERE pack_id = ?"
            params = (pack_id,)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
        return [ContentRelease.model_validate(json.loads(row[0])) for row in rows]

    async def put_listing(self, listing: MarketplaceListing) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO marketplace_listings(listing_id, payload)
                VALUES (?, ?)
                ON CONFLICT(listing_id) DO UPDATE SET payload=excluded.payload
                """,
                (listing.listing_id, listing.model_dump_json()),
            )
            await db.commit()

    async def listings(self) -> list[MarketplaceListing]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT payload FROM marketplace_listings")
            rows = await cursor.fetchall()
        return [MarketplaceListing.model_validate(json.loads(row[0])) for row in rows]
