"""Local FastAPI creator/editor service with non-blocking filesystem boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from rpg_engine import __version__
from rpg_engine.creator.catalog import canonical_kinds
from rpg_engine.creator.dependencies import DependencyResolution, resolve_dependencies
from rpg_engine.creator.lint import lint_workspace_async
from rpg_engine.creator.models import LintReport, MapGraph, MapLayout, ResourceRecord
from rpg_engine.creator.schema import schema_index
from rpg_engine.creator.web import CREATOR_HTML
from rpg_engine.creator.workspace import CreatorWorkspace


class CreatorInfo(BaseModel):
    creator_version: str
    pack_id: str
    pack_name: str
    pack_version: str
    root: str
    resource_kinds: list[str]


class MapEditorEnvelope(BaseModel):
    graph: MapGraph
    layout: MapLayout


async def _io_call(function: Any, /, *args: Any, **kwargs: Any) -> Any:
    try:
        return await asyncio.to_thread(function, *args, **kwargs)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def create_creator_app(
    workspace_path: Path | str,
    *,
    available_pack_roots: list[Path] | None = None,
    rules_plugins: Mapping[str, str] | None = None,
) -> FastAPI:
    """Create a local creator service scoped to one content-pack workspace."""

    workspace = CreatorWorkspace(workspace_path)
    available = list(available_pack_roots or [])
    plugins = dict(rules_plugins or {})
    app = FastAPI(
        title="RPG Engine Creator Platform",
        version=__version__,
        description="Schema-driven content and mod authoring service",
    )

    @app.get("/creator", response_class=HTMLResponse, include_in_schema=False)
    async def creator_ui() -> str:
        return CREATOR_HTML

    @app.get("/api/creator/v1/info", response_model=CreatorInfo)
    async def creator_info() -> CreatorInfo:
        manifest = await _io_call(workspace.manifest)
        return CreatorInfo(
            creator_version=__version__,
            pack_id=manifest.id,
            pack_name=manifest.name,
            pack_version=manifest.version,
            root=str(workspace.root),
            resource_kinds=canonical_kinds(),
        )

    @app.get("/api/creator/v1/schemas")
    async def schemas() -> dict[str, Any]:
        return schema_index()

    @app.get("/api/creator/v1/resources", response_model=list[ResourceRecord])
    async def resources(kind: str | None = Query(default=None)) -> list[ResourceRecord]:
        return await _io_call(workspace.list_resources, kind)

    @app.get(
        "/api/creator/v1/resources/{kind}/{resource_id}",
        response_model=ResourceRecord,
    )
    async def resource(kind: str, resource_id: str) -> ResourceRecord:
        return await _io_call(workspace.get, kind, resource_id)

    @app.put(
        "/api/creator/v1/resources/{kind}/{resource_id}",
        response_model=ResourceRecord,
    )
    async def put_resource(
        kind: str,
        resource_id: str,
        payload: dict[str, Any],
    ) -> ResourceRecord:
        return await _io_call(workspace.put, kind, resource_id, payload)

    @app.post(
        "/api/creator/v1/resources/{kind}/{resource_id}/template",
        response_model=ResourceRecord,
    )
    async def create_template(
        kind: str,
        resource_id: str,
        name: str | None = Query(default=None),
    ) -> ResourceRecord:
        return await _io_call(
            workspace.create_template,
            kind,
            resource_id,
            name=name,
        )

    @app.delete("/api/creator/v1/resources/{kind}/{resource_id}", status_code=204)
    async def delete_resource(kind: str, resource_id: str) -> None:
        await _io_call(workspace.delete, kind, resource_id)

    @app.get("/api/creator/v1/map", response_model=MapEditorEnvelope)
    async def map_editor() -> MapEditorEnvelope:
        graph, layout = await asyncio.gather(
            _io_call(workspace.map_graph),
            _io_call(workspace.load_map_layout),
        )
        return MapEditorEnvelope(graph=graph, layout=layout)

    @app.put("/api/creator/v1/map/layout", response_model=MapLayout)
    async def save_map_layout(layout: MapLayout) -> MapLayout:
        await _io_call(workspace.save_map_layout, layout)
        return layout

    @app.post("/api/creator/v1/validate", response_model=LintReport)
    async def validate() -> LintReport:
        return await lint_workspace_async(
            workspace.root,
            available_pack_roots=available,
            rules_plugins=plugins,
        )

    @app.get("/api/creator/v1/dependencies", response_model=DependencyResolution)
    async def dependencies() -> DependencyResolution:
        manifest = await _io_call(workspace.manifest)
        return await _io_call(
            resolve_dependencies,
            [workspace.root, *available],
            requested_ids=[manifest.id],
            rules_plugins=plugins,
        )

    return app
