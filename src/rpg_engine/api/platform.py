"""Read-only public distribution API for rpg-engine 1.x."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse

from rpg_engine import __version__
from rpg_engine.platform.models import (
    ClientRelease,
    ContentRelease,
    MarketplaceListing,
    PlatformInfo,
    ResolvedClient,
)
from rpg_engine.platform.registry import DistributionError, PlatformRegistry
from rpg_engine.platform.store import PlatformRegistryStore
from rpg_engine.public import public_contract_manifest, public_contract_schemas


def create_platform_app(
    *,
    database_path: Path | str = "rpg_platform.db",
    registry: PlatformRegistry | None = None,
    marketplace_enabled: bool = False,
) -> FastAPI:
    active_registry = registry or PlatformRegistry(PlatformRegistryStore(database_path))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await active_registry.initialize()
        yield

    app = FastAPI(
        title="RPG Engine Public Platform API",
        version=__version__,
        description="Stable v1 contracts and read-only community distribution registry.",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/v1/platform", response_model=PlatformInfo)
    async def platform_info() -> PlatformInfo:
        return PlatformInfo(
            engine_version=__version__,
            marketplace_enabled=marketplace_enabled,
            capabilities=[
                "engine-api",
                "hosted-campaigns",
                "client-distribution",
                "content-distribution",
                "creator-platform",
                "rules-plugins",
                "marketplace-metadata" if marketplace_enabled else "marketplace-disabled",
            ],
        )

    @app.get("/v1/contracts")
    async def contracts() -> dict[str, object]:
        return public_contract_manifest().model_dump(mode="json")

    @app.get("/v1/schemas")
    async def schemas() -> dict[str, object]:
        return public_contract_schemas()

    @app.get("/v1/clients", response_model=list[ClientRelease])
    async def clients() -> list[ClientRelease]:
        return await active_registry.clients()

    @app.get("/v1/clients/{client_id}/resolve", response_model=ResolvedClient)
    async def resolve_client(
        client_id: str,
        platform: str = Query(min_length=1),
        arch: str = Query(default="any", min_length=1),
        channel: str = Query(default="stable"),
    ) -> ResolvedClient:
        try:
            return await active_registry.resolve_client(
                client_id, platform=platform, arch=arch, channel=channel
            )
        except DistributionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/clients/{client_id}/download", response_class=RedirectResponse)
    async def download_client(
        client_id: str,
        platform: str = Query(min_length=1),
        arch: str = Query(default="any", min_length=1),
        channel: str = Query(default="stable"),
    ) -> RedirectResponse:
        resolved = await resolve_client(client_id, platform, arch, channel)
        return RedirectResponse(resolved.artifact.url, status_code=307)

    @app.get("/v1/content", response_model=list[ContentRelease])
    async def content() -> list[ContentRelease]:
        return await active_registry.content()

    @app.get("/v1/content/{pack_id}/resolve", response_model=ContentRelease)
    async def resolve_content(pack_id: str) -> ContentRelease:
        try:
            return await active_registry.resolve_content(pack_id)
        except DistributionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/content/{pack_id}/download", response_class=RedirectResponse)
    async def download_content(pack_id: str) -> RedirectResponse:
        release = await resolve_content(pack_id)
        return RedirectResponse(release.download_url, status_code=307)

    @app.get("/v1/marketplace")
    async def marketplace() -> dict[str, object]:
        if not marketplace_enabled:
            return {"enabled": False, "listings": []}
        listings: list[MarketplaceListing] = await active_registry.listings()
        return {
            "enabled": True,
            "listings": [item.model_dump(mode="json") for item in listings],
        }

    return app


app = create_platform_app()
