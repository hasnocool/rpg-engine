"""Typer commands for the v1 distribution registry."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from pydantic import BaseModel

from rpg_engine.api.platform import create_platform_app
from rpg_engine.platform.models import ClientRelease, ContentRelease, MarketplaceListing
from rpg_engine.platform.registry import PlatformRegistry
from rpg_engine.platform.store import PlatformRegistryStore

platform_app = typer.Typer(no_args_is_help=True, help="Public client/content distribution registry")


def _load[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    payload: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    return model.model_validate(payload)


def _registry(database: Path) -> PlatformRegistry:
    return PlatformRegistry(PlatformRegistryStore(database))


@platform_app.command("init")
def init_registry(
    database: Annotated[Path, typer.Option(help="Registry SQLite database")] = Path(
        "rpg_platform.db"
    ),
) -> None:
    async def run() -> None:
        await _registry(database).initialize()

    asyncio.run(run())
    typer.echo(str(database))


@platform_app.command("publish-client")
def publish_client(
    manifest: Annotated[Path, typer.Argument(help="Client release YAML/JSON")],
    database: Annotated[Path, typer.Option(help="Registry SQLite database")] = Path(
        "rpg_platform.db"
    ),
) -> None:
    async def run() -> None:
        registry = _registry(database)
        await registry.initialize()
        await registry.publish_client(_load(manifest, ClientRelease))

    asyncio.run(run())


@platform_app.command("publish-content")
def publish_content(
    manifest: Annotated[Path, typer.Argument(help="Content release YAML/JSON")],
    database: Annotated[Path, typer.Option(help="Registry SQLite database")] = Path(
        "rpg_platform.db"
    ),
) -> None:
    async def run() -> None:
        registry = _registry(database)
        await registry.initialize()
        await registry.publish_content(_load(manifest, ContentRelease))

    asyncio.run(run())


@platform_app.command("publish-listing")
def publish_listing(
    manifest: Annotated[Path, typer.Argument(help="Marketplace listing YAML/JSON")],
    database: Annotated[Path, typer.Option(help="Registry SQLite database")] = Path(
        "rpg_platform.db"
    ),
) -> None:
    async def run() -> None:
        registry = _registry(database)
        await registry.initialize()
        await registry.publish_listing(_load(manifest, MarketplaceListing))

    asyncio.run(run())


@platform_app.command("serve")
def serve_registry(
    database: Annotated[Path, typer.Option(help="Registry SQLite database")] = Path(
        "rpg_platform.db"
    ),
    host: Annotated[str, typer.Option(help="Bind host")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port")] = 8080,
    marketplace: Annotated[bool, typer.Option(help="Expose marketplace metadata")] = False,
) -> None:
    import uvicorn

    uvicorn.run(
        create_platform_app(database_path=database, marketplace_enabled=marketplace),
        host=host,
        port=port,
    )
