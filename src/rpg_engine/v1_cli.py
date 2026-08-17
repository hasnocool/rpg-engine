"""Unified v1 command line exposing local, hosted, creator, and platform surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from rpg_engine.api.v1 import create_hosted_app
from rpg_engine.cli import app
from rpg_engine.creator.cli import creator_app
from rpg_engine.platform.cli import platform_app

app.add_typer(creator_app, name="creator")
app.add_typer(platform_app, name="platform")


@app.command("serve-hosted")
def serve_hosted(
    host: Annotated[str, typer.Option(help="Bind host")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port")] = 8001,
    database: Annotated[Path, typer.Option(help="Shared SQLite database")] = Path(
        "rpg_engine.db"
    ),
    node_id: Annotated[str, typer.Option(help="Hosted node ID")] = "node-1",
    public_url: Annotated[str, typer.Option(help="Externally routable node URL")] = (
        "http://127.0.0.1:8001"
    ),
) -> None:
    """Run the authenticated authoritative hosted-campaign API."""

    import uvicorn

    uvicorn.run(
        create_hosted_app(
            database_path=database,
            node_id=node_id,
            public_url=public_url,
        ),
        host=host,
        port=port,
    )
