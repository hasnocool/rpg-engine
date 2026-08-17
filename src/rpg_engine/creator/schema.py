"""JSON Schema generation for creator content, manifests, and rules plugins."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from rpg_engine.content.models import ContentManifest
from rpg_engine.creator.catalog import RESOURCE_SPECS, resource_spec
from rpg_engine.creator.models import ModMetadata
from rpg_engine.rules.plugin import RulesPluginDescriptor

SCHEMA_BUNDLE_VERSION = 1


def schema_for_kind(kind: str) -> dict[str, Any]:
    spec = resource_spec(kind)
    schema = spec.model.model_json_schema()
    schema["$id"] = f"https://rpg-engine.local/schemas/v1/{spec.kind}.json"
    schema["title"] = spec.title
    return schema


def schema_index() -> dict[str, Any]:
    """Return a discoverable schema catalog for editors and external tooling."""

    return {
        "schema_bundle_version": SCHEMA_BUNDLE_VERSION,
        "manifest": ContentManifest.model_json_schema(),
        "mod": ModMetadata.model_json_schema(),
        "rules_plugin": RulesPluginDescriptor.model_json_schema(),
        "resources": {
            spec.kind: {
                "directory": spec.directory,
                "title": spec.title,
                "aliases": list(spec.aliases),
                "schema": schema_for_kind(spec.kind),
            }
            for spec in RESOURCE_SPECS
        },
    }


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def write_schema_bundle(output_dir: Path | str) -> list[Path]:
    """Write standalone schemas plus an index for IDE/editor integration."""

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for spec in RESOURCE_SPECS:
        path = output / f"{spec.kind}.schema.json"
        _atomic_write_json(path, schema_for_kind(spec.kind))
        written.append(path)
    extras = {
        "manifest.schema.json": ContentManifest.model_json_schema(),
        "mod.schema.json": ModMetadata.model_json_schema(),
        "rules-plugin.schema.json": RulesPluginDescriptor.model_json_schema(),
        "index.json": schema_index(),
    }
    for filename, payload in extras.items():
        path = output / filename
        _atomic_write_json(path, payload)
        written.append(path)
    return written


async def write_schema_bundle_async(output_dir: Path | str) -> list[Path]:
    return await asyncio.to_thread(write_schema_bundle, output_dir)
