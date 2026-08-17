"""CLI adapter for demos, inspection, creator tooling, and running the API server."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from rpg_engine.commands import AttackTargetCommand, CreateEntityCommand
from rpg_engine.content.loader import load_content_pack_async
from rpg_engine.creator.cli import creator_app
from rpg_engine.engine import SimulationEngine
from rpg_engine.models import Entity, Health, Identity, Stats, WorldState

app = typer.Typer(no_args_is_help=True, help="Headless deterministic RPG simulation engine")
app.add_typer(creator_app, name="creator")


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
    """Run the authoritative FastAPI/WebSocket service."""

    import uvicorn

    uvicorn.run("rpg_engine.api.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
