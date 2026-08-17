"""YAML content-pack loading with async wrappers for server use."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import yaml

from rpg_engine.content.models import ContentManifest, ContentRegistry, EffectSpec
from rpg_engine.models import WeaponSpec


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected mapping in {path}")
    return payload


def load_content_pack(root: Path) -> ContentRegistry:
    registry = ContentRegistry.with_core_defaults()
    manifest_path = root / "manifest.yaml"
    if manifest_path.exists():
        registry.manifest = ContentManifest.model_validate(_read_yaml(manifest_path))

    items_dir = root / "items"
    if items_dir.exists():
        for path in sorted(items_dir.glob("*.yaml")):
            weapon = WeaponSpec.model_validate(_read_yaml(path))
            registry.weapons[weapon.id] = weapon

    effects_dir = root / "effects"
    if effects_dir.exists():
        for path in sorted(effects_dir.glob("*.yaml")):
            effect = EffectSpec.model_validate(_read_yaml(path))
            registry.effects[effect.id] = effect
    return registry


async def load_content_pack_async(root: Path) -> ContentRegistry:
    """Load filesystem content without blocking an active event loop."""

    return await asyncio.to_thread(load_content_pack, root)
