"""Content-pack and rules-plugin dependency resolution for creator/mod workflows."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import Field

from rpg_engine import __version__
from rpg_engine.content.models import ContentManifest
from rpg_engine.creator.models import ModMetadata
from rpg_engine.models import StrictModel
from rpg_engine.versioning import parsed_version, require_version


class PackDescriptor(StrictModel):
    id: str
    name: str
    version: str
    ruleset: str
    root: Path
    mod: ModMetadata = Field(default_factory=lambda: ModMetadata(engine="*"))


class DependencyResolution(StrictModel):
    requested_ids: list[str] = Field(default_factory=list)
    order: list[str] = Field(default_factory=list)
    packages: dict[str, PackDescriptor] = Field(default_factory=dict)

    @property
    def roots_in_load_order(self) -> list[Path]:
        return [self.packages[pack_id].root for pack_id in self.order]


def _read_mapping(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected mapping in {path}")
    return payload


def load_pack_descriptor(root: Path) -> PackDescriptor:
    """Read a runtime manifest plus optional v0.9 ``mod.yaml`` metadata."""

    root = root.resolve()
    manifest_path = root / "manifest.yaml"
    if not manifest_path.is_file():
        raise ValueError(f"content pack is missing manifest.yaml: {root}")
    manifest = ContentManifest.model_validate(_read_mapping(manifest_path))
    parsed_version(manifest.version)

    mod_path = root / "mod.yaml"
    mod = (
        ModMetadata.model_validate(_read_mapping(mod_path))
        if mod_path.is_file()
        else ModMetadata(engine="*")
    )
    return PackDescriptor(
        id=manifest.id,
        name=manifest.name,
        version=manifest.version,
        ruleset=manifest.ruleset,
        root=root,
        mod=mod,
    )


def _validate_rules_plugins(
    package: PackDescriptor,
    rules_plugins: Mapping[str, str],
) -> None:
    for requirement in package.mod.rules_plugins:
        installed = rules_plugins.get(requirement.id)
        if installed is None:
            if requirement.optional:
                continue
            raise ValueError(
                f"content pack {package.id} requires rules plugin {requirement.id} "
                f"{requirement.version}"
            )
        require_version(
            installed,
            requirement.version,
            subject=f"rules plugin {requirement.id}",
        )


def resolve_dependencies(
    roots: list[Path],
    *,
    requested_ids: list[str] | None = None,
    engine_version: str = __version__,
    rules_plugins: Mapping[str, str] | None = None,
) -> DependencyResolution:
    """Resolve dependency order with version, engine, cycle, and plugin checks."""

    packages: dict[str, PackDescriptor] = {}
    for root in roots:
        package = load_pack_descriptor(root)
        if package.id in packages:
            previous = packages[package.id]
            raise ValueError(
                f"duplicate content pack id {package.id}: {previous.root} and {package.root}"
            )
        packages[package.id] = package

    requested = requested_ids or sorted(packages)
    unknown_requested = sorted(set(requested) - set(packages))
    if unknown_requested:
        raise ValueError(f"unknown requested content packs: {', '.join(unknown_requested)}")

    plugin_versions = rules_plugins or {}
    for package in packages.values():
        require_version(
            engine_version,
            package.mod.engine,
            subject=f"engine for content pack {package.id}",
        )
        _validate_rules_plugins(package, plugin_versions)

    visiting: list[str] = []
    visited: set[str] = set()
    order: list[str] = []

    def visit(pack_id: str) -> None:
        if pack_id in visited:
            return
        if pack_id in visiting:
            cycle_start = visiting.index(pack_id)
            cycle = [*visiting[cycle_start:], pack_id]
            raise ValueError(f"content dependency cycle: {' -> '.join(cycle)}")

        package = packages[pack_id]
        visiting.append(pack_id)
        for requirement in package.mod.dependencies:
            dependency = packages.get(requirement.id)
            if dependency is None:
                if requirement.optional:
                    continue
                raise ValueError(
                    f"content pack {package.id} requires missing pack "
                    f"{requirement.id} {requirement.version}"
                )
            require_version(
                dependency.version,
                requirement.version,
                subject=f"content pack {requirement.id}",
            )
            visit(requirement.id)
        visiting.pop()
        visited.add(pack_id)
        order.append(pack_id)

    for pack_id in requested:
        visit(pack_id)

    return DependencyResolution(
        requested_ids=list(requested),
        order=order,
        packages={pack_id: packages[pack_id] for pack_id in order},
    )


async def resolve_dependencies_async(
    roots: list[Path],
    *,
    requested_ids: list[str] | None = None,
    engine_version: str = __version__,
    rules_plugins: Mapping[str, str] | None = None,
) -> DependencyResolution:
    """Resolve pack metadata without blocking an active server event loop."""

    return await asyncio.to_thread(
        resolve_dependencies,
        roots,
        requested_ids=requested_ids,
        engine_version=engine_version,
        rules_plugins=rules_plugins,
    )
