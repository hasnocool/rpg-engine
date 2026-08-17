"""CLI, TUI, API, and SSH entrypoints for the headless RPG engine."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from prompt_toolkit import PromptSession
from rich.console import Console

from rpg_engine.api.app import create_app
from rpg_engine.clients.http import HttpCampaignClient
from rpg_engine.commands import AttackTargetCommand, CreateEntityCommand
from rpg_engine.content.loader import load_content_pack_async
from rpg_engine.engine import SimulationEngine
from rpg_engine.models import Entity, Health, Identity, Stats, WorldState
from rpg_engine.persistence.sqlite import SQLiteEventStore
from rpg_engine.service import CampaignService
from rpg_engine.ssh_server import SSHServerConfig, create_ssh_listener, create_ssh_server
from rpg_engine.terminal import TerminalSession

app = typer.Typer(no_args_is_help=True, help="Headless deterministic RPG simulation engine")


@app.command()
def demo(
    seed: Annotated[int, typer.Option(help="Deterministic campaign seed")] = 918392482,
) -> None:
    """Run a tiny deterministic combat demo entirely in-process."""

    async def _run() -> None:
        content = await load_content_pack_async(Path("content/core"))
        world = WorldState(campaign_id="demo", seed=seed)
        engine = SimulationEngine(world, content=content)
        fighter = Entity(
            id="fighter-1",
            identity=Identity(name="Aric", tags={"humanoid", "hero"}),
            stats=Stats(strength=16, dexterity=12, armor_class=16),
            health=Health(current=24, maximum=24),
        )
        goblin = Entity(
            id="goblin-1",
            identity=Identity(name="Goblin", tags={"humanoid", "monster"}),
            stats=Stats(strength=8, dexterity=14, armor_class=13),
            health=Health(current=11, maximum=11),
        )
        engine.execute(CreateEntityCommand(entity=fighter))
        engine.execute(CreateEntityCommand(entity=goblin))
        events = engine.execute(
            AttackTargetCommand(
                attacker_id="fighter-1", target_id="goblin-1", weapon_id="longsword"
            )
        )
        for event in events:
            typer.echo(event.model_dump_json(indent=2))

    asyncio.run(_run())


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind host")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port")] = 8000,
    reload: Annotated[bool, typer.Option(help="Enable development reload")] = False,
) -> None:
    """Run the authoritative REST/WebSocket/browser service."""

    import uvicorn

    uvicorn.run("rpg_engine.api.app:app", host=host, port=port, reload=reload)


@app.command()
def play(
    campaign: Annotated[str, typer.Option(help="Campaign ID")],
    server: Annotated[str, typer.Option(help="RPG Engine API base URL")] = "http://127.0.0.1:8000",
    actor: Annotated[str | None, typer.Option(help="Optional observation actor ID")] = None,
) -> None:
    """Open the non-blocking interactive terminal client against the v1 API."""

    async def _run() -> None:
        client = HttpCampaignClient(server, campaign)
        terminal = TerminalSession(client, actor_id=actor)
        prompt: PromptSession[str] = PromptSession()
        console = Console()
        try:
            console.print(await terminal.banner())
            while True:
                line = await prompt.prompt_async("rpg> ")
                try:
                    reply = await terminal.handle(line)
                except Exception as exc:
                    console.print(f"[red]ERROR:[/red] {exc}")
                    continue
                if reply.text:
                    console.print(reply.text)
                if reply.close:
                    break
        finally:
            await client.close()

    asyncio.run(_run())


@app.command("tui")
def tui_command(
    campaign: Annotated[str, typer.Option(help="Campaign ID")],
    server: Annotated[str, typer.Option(help="RPG Engine API base URL")] = "http://127.0.0.1:8000",
    actor: Annotated[str | None, typer.Option(help="Optional observation actor ID")] = None,
) -> None:
    """Launch the Textual TUI adapter."""

    from rpg_engine.tui import RPGTUI

    RPGTUI(server, campaign, actor_id=actor).run()


@app.command("serve-ssh")
def serve_ssh(
    host: Annotated[str, typer.Option(help="SSH bind host")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="SSH bind port")] = 8022,
    database: Annotated[Path, typer.Option(help="SQLite database path")] = Path("rpg_engine.db"),
    content: Annotated[Path, typer.Option(help="Content pack path")] = Path("content/core"),
    host_key: Annotated[
        Path, typer.Option(help="SSH server private host key")
    ] = Path("ssh_host_key"),
    authorized_keys: Annotated[
        Path, typer.Option(help="OpenSSH authorized_keys file for client authentication")
    ] = Path("authorized_keys"),
    campaign: Annotated[
        str | None, typer.Option(help="Optional fixed campaign for all SSH sessions")
    ] = None,
    actor_from_username: Annotated[
        bool, typer.Option(help="Use authenticated SSH username as observation actor ID")
    ] = False,
) -> None:
    """Run an authenticated SSH RPG terminal. It never exposes a host operating-system shell."""

    async def _run() -> None:
        listener = await create_ssh_server(
            SSHServerConfig(
                host=host,
                port=port,
                host_key=host_key,
                authorized_keys=authorized_keys,
                database_path=database,
                content_path=content,
                campaign_id=campaign,
                actor_from_username=actor_from_username,
            )
        )
        try:
            await asyncio.Future()
        finally:
            listener.close()
            await listener.wait_closed()

    asyncio.run(_run())


@app.command("serve-all")
def serve_all(
    api_host: Annotated[str, typer.Option(help="API bind host")] = "127.0.0.1",
    api_port: Annotated[int, typer.Option(help="API bind port")] = 8000,
    ssh_host: Annotated[str, typer.Option(help="SSH bind host")] = "127.0.0.1",
    ssh_port: Annotated[int, typer.Option(help="SSH bind port")] = 8022,
    database: Annotated[
        Path, typer.Option(help="Shared SQLite database path")
    ] = Path("rpg_engine.db"),
    content: Annotated[Path, typer.Option(help="Content pack path")] = Path("content/core"),
    host_key: Annotated[
        Path, typer.Option(help="SSH server private host key")
    ] = Path("ssh_host_key"),
    authorized_keys: Annotated[
        Path, typer.Option(help="OpenSSH authorized_keys file for client authentication")
    ] = Path("authorized_keys"),
    campaign: Annotated[str | None, typer.Option(help="Optional fixed SSH campaign")] = None,
) -> None:
    """Run REST/WebSocket/browser and SSH transports on one shared authority service."""

    async def _run() -> None:
        import uvicorn

        store = SQLiteEventStore(database)
        await store.initialize()
        registry = await load_content_pack_async(content)
        service = CampaignService(store, content=registry)
        api = create_app(campaign_service=service)
        api_server = uvicorn.Server(
            uvicorn.Config(api, host=api_host, port=api_port, loop="asyncio")
        )
        ssh_listener = await create_ssh_listener(
            service,
            SSHServerConfig(
                host=ssh_host,
                port=ssh_port,
                host_key=host_key,
                authorized_keys=authorized_keys,
                database_path=database,
                content_path=content,
                campaign_id=campaign,
            ),
        )
        try:
            await api_server.serve()
        finally:
            ssh_listener.close()
            await ssh_listener.wait_closed()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
