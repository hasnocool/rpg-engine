"""Filesystem-backed Creator Platform workspace with validated atomic writes."""

from __future__ import annotations

import os
import re
import tempfile
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from rpg_engine.content.loader import load_content_pack
from rpg_engine.content.models import ContentManifest, ContentRegistry
from rpg_engine.creator.catalog import RESOURCE_SPECS, resource_spec
from rpg_engine.creator.models import (
    CampaignDraft,
    MapEdge,
    MapGraph,
    MapLayout,
    MapNode,
    ModMetadata,
    ResourceRecord,
)

_RESOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _read_mapping(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected mapping in {path}")
    return payload


def _json_payload(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=True)


class CreatorWorkspace:
    """Validated CRUD facade for content YAML and creator-only metadata."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        self._lock = threading.RLock()

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.yaml"

    @property
    def mod_path(self) -> Path:
        return self.root / "mod.yaml"

    @property
    def layout_path(self) -> Path:
        return self.root / ".creator" / "map-layout.yaml"

    def _validate_id(self, resource_id: str) -> str:
        if not _RESOURCE_ID.fullmatch(resource_id):
            raise ValueError(
                "resource ids must contain only letters, digits, '.', '_', or '-' "
                "and cannot start with punctuation"
            )
        return resource_id

    def _resource_path(self, kind: str, resource_id: str) -> Path:
        spec = resource_spec(kind)
        return self.root / spec.directory / f"{self._validate_id(resource_id)}.yaml"

    def _atomic_write_yaml(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        rendered = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(rendered)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except BaseException:
            with suppress(FileNotFoundError):
                os.unlink(temp_name)
            raise

    def initialize(
        self,
        *,
        pack_id: str,
        name: str,
        version: str = "0.1.0",
        ruleset: str = "d20",
        engine: str = ">=1,<2",
        force: bool = False,
    ) -> None:
        self._validate_id(pack_id)
        with self._lock:
            if self.root.exists() and any(self.root.iterdir()) and not force:
                raise FileExistsError(f"workspace is not empty: {self.root}")
            self.root.mkdir(parents=True, exist_ok=True)
            manifest = ContentManifest(id=pack_id, name=name, version=version, ruleset=ruleset)
            self._atomic_write_yaml(self.manifest_path, _json_payload(manifest))
            self._atomic_write_yaml(self.mod_path, _json_payload(ModMetadata(engine=engine)))
            for spec in RESOURCE_SPECS:
                (self.root / spec.directory).mkdir(parents=True, exist_ok=True)
            self.layout_path.parent.mkdir(parents=True, exist_ok=True)

    def manifest(self) -> ContentManifest:
        return ContentManifest.model_validate(_read_mapping(self.manifest_path))

    def mod_metadata(self) -> ModMetadata:
        if not self.mod_path.is_file():
            return ModMetadata(engine="*")
        return ModMetadata.model_validate(_read_mapping(self.mod_path))

    def set_mod_metadata(self, metadata: ModMetadata) -> None:
        with self._lock:
            self._atomic_write_yaml(self.mod_path, _json_payload(metadata))

    def list_resources(self, kind: str | None = None) -> list[ResourceRecord]:
        specs = [resource_spec(kind)] if kind is not None else list(RESOURCE_SPECS)
        records: list[ResourceRecord] = []
        with self._lock:
            for spec in specs:
                directory = self.root / spec.directory
                if not directory.is_dir():
                    continue
                for path in sorted(directory.glob("*.yaml")):
                    payload = _read_mapping(path)
                    validated = spec.model.model_validate(payload)
                    dumped = validated.model_dump(mode="json", exclude_none=True)
                    resource_id = str(dumped.get("id", path.stem))
                    name = dumped.get("name") or dumped.get("title")
                    records.append(
                        ResourceRecord(
                            kind=spec.kind,
                            id=resource_id,
                            relative_path=str(path.relative_to(self.root)),
                            name=str(name) if name is not None else None,
                        )
                    )
        return records

    def get(self, kind: str, resource_id: str) -> ResourceRecord:
        spec = resource_spec(kind)
        path = self._resource_path(kind, resource_id)
        with self._lock:
            if not path.is_file():
                raise KeyError(f"unknown {spec.kind}: {resource_id}")
            validated = spec.model.model_validate(_read_mapping(path))
            dumped = validated.model_dump(mode="json", exclude_none=True)
        actual_id = str(dumped.get("id", resource_id))
        if actual_id != resource_id:
            raise ValueError(
                f"resource id {actual_id!r} does not match filename id {resource_id!r}"
            )
        name = dumped.get("name") or dumped.get("title")
        return ResourceRecord(
            kind=spec.kind,
            id=resource_id,
            relative_path=str(path.relative_to(self.root)),
            name=str(name) if name is not None else None,
            payload=dumped,
        )

    def put(self, kind: str, resource_id: str, payload: dict[str, Any]) -> ResourceRecord:
        spec = resource_spec(kind)
        candidate = dict(payload)
        candidate.setdefault("id", resource_id)
        validated = spec.model.model_validate(candidate)
        dumped = validated.model_dump(mode="json", exclude_none=True)
        actual_id = str(dumped.get("id", resource_id))
        if actual_id != resource_id:
            raise ValueError(
                f"payload id {actual_id!r} does not match requested id {resource_id!r}"
            )
        with self._lock:
            self._atomic_write_yaml(self._resource_path(kind, resource_id), dumped)
        return self.get(spec.kind, resource_id)

    def create_template(
        self, kind: str, resource_id: str, *, name: str | None = None
    ) -> ResourceRecord:
        spec = resource_spec(kind)
        path = self._resource_path(spec.kind, resource_id)
        if path.exists():
            raise FileExistsError(f"resource already exists: {spec.kind}/{resource_id}")
        payload = spec.template(resource_id, name or resource_id.replace("_", " ").title())
        return self.put(spec.kind, resource_id, payload)

    def delete(self, kind: str, resource_id: str) -> None:
        path = self._resource_path(kind, resource_id)
        with self._lock:
            try:
                path.unlink()
            except FileNotFoundError as exc:
                raise KeyError(f"unknown {resource_spec(kind).kind}: {resource_id}") from exc

    def load_registry(self) -> ContentRegistry:
        return load_content_pack(self.root)

    def load_map_layout(self) -> MapLayout:
        with self._lock:
            if not self.layout_path.is_file():
                return MapLayout()
            return MapLayout.model_validate(_read_mapping(self.layout_path))

    def save_map_layout(self, layout: MapLayout) -> None:
        with self._lock:
            self._atomic_write_yaml(self.layout_path, _json_payload(layout))

    def map_graph(self) -> MapGraph:
        layout = self.load_map_layout()
        nodes: list[MapNode] = []
        for record in self.list_resources("location"):
            payload = self.get("location", record.id).payload or {}
            point = layout.positions.get(record.id)
            nodes.append(
                MapNode(
                    id=record.id,
                    name=str(payload.get("name", record.id)),
                    region=str(payload["region"]) if payload.get("region") is not None else None,
                    x=point.x if point is not None else None,
                    y=point.y if point is not None else None,
                )
            )
        edges: list[MapEdge] = []
        for record in self.list_resources("connection"):
            payload = self.get("connection", record.id).payload or {}
            edges.append(
                MapEdge(
                    id=record.id,
                    from_location_id=str(payload["from_location_id"]),
                    to_location_id=str(payload["to_location_id"]),
                    bidirectional=bool(payload.get("bidirectional", True)),
                    hidden=bool(payload.get("hidden", False)),
                    travel_minutes=int(payload.get("travel_minutes", 10)),
                )
            )
        return MapGraph(
            nodes=sorted(nodes, key=lambda item: item.id),
            edges=sorted(edges, key=lambda item: item.id),
        )

    def connect_locations(
        self,
        connection_id: str,
        *,
        from_location_id: str,
        to_location_id: str,
        travel_minutes: int = 10,
        bidirectional: bool = True,
        hidden: bool = False,
    ) -> ResourceRecord:
        if from_location_id == to_location_id:
            raise ValueError("a map connection must connect two different locations")
        self.get("location", from_location_id)
        self.get("location", to_location_id)
        return self.put(
            "connection",
            connection_id,
            {
                "id": connection_id,
                "from_location_id": from_location_id,
                "to_location_id": to_location_id,
                "travel_minutes": travel_minutes,
                "bidirectional": bidirectional,
                "hidden": hidden,
            },
        )

    def campaign_drafts(self) -> list[CampaignDraft]:
        return [
            CampaignDraft.model_validate(self.get("campaign", record.id).payload)
            for record in self.list_resources("campaign")
        ]
