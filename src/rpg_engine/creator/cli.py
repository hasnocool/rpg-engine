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
    force: Annotated[bool, typer.Option(help="Allow initializing a non-empty directory")] = False,
) -> None:
    """Scaffold a content pack with runtime manifest, mod metadata, and editor directories."""

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
    available: Annotated[
        list[Path] | None,
        typer.Option("--available", help="Additional dependency pack root; repeatable"),
    ] = None,
    discover_plugins: Annotated[
        bool, typer.Option(help="Discover installed rules plugins for requirement checks")
    ] = False,
) -> None:
    """Validate schemas, cross-references, graph quality, and dependency constraints."""

    plugin_versions: dict[str, str] = {}
    if discover_plugins:
        plugin_versions = RulesPluginRegistry().discover().versions
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
    kind: Annotated[
        str | None, typer.Option(help="Write one resource schema instead of the full bundle")
    ] = None,
) -> None:
    """Generate JSON Schema for IDEs, CI, forms, and external creator tools."""

    if kind is None:
        written = write_schema_bundle(output)
        typer.echo(f"Wrote {len(written)} schema files to {output.resolve()}")
        return
    output.mkdir(parents=True, exist_ok=True)
    schema = schema_for_kind(kind)
    path = output / f"{kind}.schema.json"
    path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    typer.echo(str(path.resolve()))


@creator_app.command("list")
def list_resources(
    path: Annotated[Path, typer.Argument(help="Content-pack directory")],
    kind: Annotated[str | None, typer.Option(help="Optional resource kind filter")] = None,
) -> None:
    workspace = CreatorWorkspace(path)
    for record in workspace.list_resources(kind):
        typer.echo(f"{record.kind}\t{record.id}\t{record.relative_path}")


@creator_app.command("show")
def show_resource(
    path: Annotated[Path, typer.Argument(help="Content-pack directory")],
    kind: Annotated[str, typer.Argument(help="Resource kind")],
    resource_id: Annotated[str, typer.Argument(help="Resource ID")],
) -> None:
    record = CreatorWorkspace(path).get(kind, resource_id)
    typer.echo(json.dumps(record.payload, indent=2, sort_keys=True))


@creator_app.command("new")
def new_resource(
    path: Annotated[Path, typer.Argument(help="Content-pack directory")],
    kind: Annotated[str, typer.Argument(help="Resource kind")],
    resource_id: Annotated[str, typer.Argument(help="Resource ID")],
    name: Annotated[str | None, typer.Option(help="Starter display name")] = None,
) -> None:
    record = CreatorWorkspace(path).create_template(kind, resource_id, name=name)
    typer.echo(record.relative_path)


@creator_app.command("connect")
def connect_locations(
    path: Annotated[Path, typer.Argument(help="Content-pack directory")],
    connection_id: Annotated[str, typer.Argument(help="New connection ID")],
    source: Annotated[str, typer.Option("--from", help="Source location ID")],
    destination: Annotated[str, typer.Option("--to", help="Destination location ID")],
    minutes: Annotated[int, typer.Option(help="Travel time in minutes")] = 10,
    one_way: Annotated[bool, typer.Option(help="Create a one-way connection")] = False,
    hidden: Annotated[bool, typer.Option(help="Connection starts hidden")] = False,
) -> None:
    record = CreatorWorkspace(path).connect_locations(
        connection_id,
        from_location_id=source,
        to_location_id=destination,
        travel_minutes=minutes,
        bidirectional=not one_way,
        hidden=hidden,
    )
    typer.echo(record.relative_path)


@creator_app.command("deps")
def dependency_graph(
    path: Annotated[Path, typer.Argument(help="Root content-pack directory")],
    available: Annotated[
        list[Path] | None,
        typer.Option("--available", help="Dependency pack root; repeatable"),
    ] = None,
    discover_plugins: Annotated[
        bool, typer.Option(help="Discover installed rules plugins")
    ] = False,
) -> None:
    workspace = CreatorWorkspace(path)
    manifest = workspace.manifest()
    plugin_versions = RulesPluginRegistry().discover().versions if discover_plugins else {}
    resolution = resolve_dependencies(
        [workspace.root, *(available or [])],
        requested_ids=[manifest.id],
        rules_plugins=plugin_versions,
    )
    for index, pack_id in enumerate(resolution.order, start=1):
        package = resolution.packages[pack_id]
        typer.echo(f"{index}. {package.id} {package.version} {package.root}")


@creator_app.command("plugins")
def rules_plugins() -> None:
    """Discover and validate installed rules plugins."""

    registry = RulesPluginRegistry().discover()
    for plugin_id, plugin in sorted(registry.plugins.items()):
        descriptor = plugin.descriptor
        typer.echo(f"{plugin_id}\t{descriptor.version}\t{descriptor.name}")


@creator_app.command("serve")
def serve_creator(
    path: Annotated[Path, typer.Argument(help="Content-pack directory")],
    host: Annotated[str, typer.Option(help="Bind host")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port")] = 8010,
    available: Annotated[
        list[Path] | None,
        typer.Option("--available", help="Dependency pack root; repeatable"),
    ] = None,
    discover_plugins: Annotated[
        bool, typer.Option(help="Discover installed rules plugins")
    ] = False,
) -> None:
    """Run the local browser/API campaign, map, creature, item, and effect editor."""

    import uvicorn

    plugin_versions = RulesPluginRegistry().discover().versions if discover_plugins else {}
    app = create_creator_app(
        path,
        available_pack_roots=available or [],
        rules_plugins=plugin_versions,
    )
    uvicorn.run(app, host=host, port=port)
