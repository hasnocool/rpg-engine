"""Typer commands for the stable v1 Creator Platform."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from rpg_engine.creator.app import create_creator_app
from rpg_engine.creator.dependencies import resolve_dependencies
from rpg_engine.creator.lint import lint_workspace
from rpg_engine.creator.schema import schema_for_kind, write_schema_bundle
from rpg_engine.creator.workspace import CreatorWorkspace
from rpg_engine.rules.plugin import RulesPluginRegistry

creator_app = typer.Typer(no_args_is_help=True, help="Content/mod creator SDK and editor tools")


@creator_app.command("init")
def init_workspace(
    path: Annotated[Path, typer.Argument(help="New content-pack directory")],
    pack_id: Annotated[str, typer.Option("--id", help="Content-pack ID")],
    name: Annotated[str, typer.Option(help="Human-readable pack name")],
    version: Annotated[str, typer.Option(help="Initial pack version")] = "0.1.0",
    ruleset: Annotated[str, typer.Option(help="Default ruleset ID")] = "d20",
    engine: Annotated[str, typer.Option(help="Engine version constraint")] = ">=1,<2",
    force: Annotated[bool, typer.Option(help="Allow a non-empty directory")] = False,
) -> None:
    workspace = CreatorWorkspace(path)
    workspace.initialize(
        pack_id=pack_id,
        name=name,
        version=version,
        ruleset=ruleset,
        engine=engine,
        force=force,
    )
    typer.echo(f"Initialized {pack_id} at {workspace.root}")


@creator_app.command("validate")
def validate_workspace(
    path: Annotated[Path, typer.Argument(help="Content-pack directory")],
    available: Annotated[list[Path] | None, typer.Option("--available")] = None,
    discover_plugins: Annotated[bool, typer.Option()] = False,
) -> None:
    plugin_versions = RulesPluginRegistry().discover().versions if discover_plugins else {}
    report = lint_workspace(
        path,
        available_pack_roots=available or [],
        rules_plugins=plugin_versions,
    )
    for issue in report.issues:
        location = f" [{issue.path}]" if issue.path else ""
        typer.echo(f"{issue.severity.value.upper()} {issue.code}: {issue.message}{location}")
    typer.echo(json.dumps(report.stats, sort_keys=True))
    if not report.valid:
        raise typer.Exit(code=1)


@creator_app.command("schema")
def schema_command(
    output: Annotated[Path, typer.Option(help="Schema output directory")] = Path("schemas"),
    kind: Annotated[str | None, typer.Option()] = None,
) -> None:
    if kind is None:
        for path in write_schema_bundle(output):
            typer.echo(path)
        return
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"{kind}.schema.json"
    path.write_text(json.dumps(schema_for_kind(kind), indent=2) + "\n", encoding="utf-8")
    typer.echo(path)


@creator_app.command("list")
def list_resources(
    path: Annotated[Path, typer.Argument()],
    kind: Annotated[str | None, typer.Option()] = None,
) -> None:
    for record in CreatorWorkspace(path).list_resources(kind):
        typer.echo(f"{record.kind}\t{record.id}\t{record.relative_path}")


@creator_app.command("show")
def show_resource(
    path: Annotated[Path, typer.Argument()],
    kind: Annotated[str, typer.Argument()],
    resource_id: Annotated[str, typer.Argument()],
) -> None:
    record = CreatorWorkspace(path).get(kind, resource_id)
    typer.echo(json.dumps(record.payload, indent=2, sort_keys=True))


@creator_app.command("new")
def new_resource(
    path: Annotated[Path, typer.Argument()],
    kind: Annotated[str, typer.Argument()],
    resource_id: Annotated[str, typer.Argument()],
    name: Annotated[str | None, typer.Option()] = None,
) -> None:
    record = CreatorWorkspace(path).create_template(kind, resource_id, name=name)
    typer.echo(record.relative_path)


@creator_app.command("connect")
def connect(
    path: Annotated[Path, typer.Argument()],
    connection_id: Annotated[str, typer.Argument()],
    source: Annotated[str, typer.Option("--from")],
    destination: Annotated[str, typer.Option("--to")],
    minutes: Annotated[int, typer.Option()] = 10,
    hidden: Annotated[bool, typer.Option()] = False,
) -> None:
    record = CreatorWorkspace(path).connect_locations(
        connection_id,
        from_location_id=source,
        to_location_id=destination,
        travel_minutes=minutes,
        hidden=hidden,
    )
    typer.echo(record.relative_path)


@creator_app.command("deps")
def dependencies(
    path: Annotated[Path, typer.Argument()],
    available: Annotated[list[Path] | None, typer.Option("--available")] = None,
) -> None:
    workspace = CreatorWorkspace(path)
    result = resolve_dependencies(
        [workspace.root, *(available or [])],
        requested_ids=[workspace.manifest().id],
        rules_plugins=RulesPluginRegistry().discover().versions,
    )
    typer.echo(result.model_dump_json(indent=2))


@creator_app.command("plugins")
def plugins() -> None:
    registry = RulesPluginRegistry().discover()
    for plugin_id, version in registry.versions.items():
        typer.echo(f"{plugin_id}\t{version}")


@creator_app.command("serve")
def serve(
    path: Annotated[Path, typer.Argument()],
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8010,
) -> None:
    import uvicorn

    uvicorn.run(create_creator_app(path), host=host, port=port)
