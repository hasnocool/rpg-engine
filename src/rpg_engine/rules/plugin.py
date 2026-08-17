"""Stable rules plugin SDK for rpg-engine 1.x."""

from __future__ import annotations

import asyncio
from importlib import metadata
from typing import ClassVar, Protocol, runtime_checkable

from pydantic import Field

from rpg_engine import __version__
from rpg_engine.models import StrictModel
from rpg_engine.rules.base import RulesRuntime
from rpg_engine.rules.d20 import D20RulesRuntime
from rpg_engine.versioning import VersionRequirement, parsed_version, require_version

RULES_PLUGIN_API_VERSION = "1"
RULES_PLUGIN_ENTRY_POINT = "rpg_engine.rules_plugins"


class RulesPluginDescriptor(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    name: str
    version: str
    api_version: str = RULES_PLUGIN_API_VERSION
    engine: str = ">=1,<2"
    description: str = ""


@runtime_checkable
class RulesPlugin(Protocol):
    descriptor: RulesPluginDescriptor

    def create_runtime(self) -> RulesRuntime: ...


class BuiltinD20RulesPlugin:
    descriptor: ClassVar[RulesPluginDescriptor] = RulesPluginDescriptor(
        id="d20",
        name="Built-in generic d20 rules",
        version="1.0.0",
        engine=">=1,<2",
        description="Reference generic d20 runtime shipped with rpg-engine.",
    )

    def create_runtime(self) -> RulesRuntime:
        return D20RulesRuntime()


class RulesPluginRegistry:
    """Validated plugin catalog covered by the stable rules API v1 contract."""

    def __init__(self, *, engine_version: str = __version__) -> None:
        self.engine_version = engine_version
        self._plugins: dict[str, RulesPlugin] = {}

    @property
    def plugins(self) -> dict[str, RulesPlugin]:
        return dict(self._plugins)

    @property
    def versions(self) -> dict[str, str]:
        return {
            plugin_id: plugin.descriptor.version
            for plugin_id, plugin in sorted(self._plugins.items())
        }

    def register(self, plugin: RulesPlugin) -> None:
        if not isinstance(plugin, RulesPlugin):
            raise TypeError("rules plugin must expose descriptor and create_runtime()")
        descriptor = plugin.descriptor
        parsed_version(descriptor.version)
        if descriptor.api_version != RULES_PLUGIN_API_VERSION:
            raise ValueError(
                f"rules plugin {descriptor.id} uses API {descriptor.api_version}; "
                f"expected {RULES_PLUGIN_API_VERSION}"
            )
        require_version(
            self.engine_version,
            descriptor.engine,
            subject=f"engine for rules plugin {descriptor.id}",
        )
        if descriptor.id in self._plugins:
            raise ValueError(f"duplicate rules plugin id: {descriptor.id}")
        runtime = plugin.create_runtime()
        if not isinstance(runtime, RulesRuntime):
            raise TypeError(f"rules plugin {descriptor.id} did not create a RulesRuntime")
        self._plugins[descriptor.id] = plugin

    def runtime(self, plugin_id: str) -> RulesRuntime:
        try:
            return self._plugins[plugin_id].create_runtime()
        except KeyError as exc:
            raise KeyError(f"unknown rules plugin: {plugin_id}") from exc

    def validate_requirements(self, requirements: list[VersionRequirement]) -> None:
        for requirement in requirements:
            plugin = self._plugins.get(requirement.id)
            if plugin is None:
                if requirement.optional:
                    continue
                raise ValueError(
                    f"missing rules plugin {requirement.id} {requirement.version}"
                )
            require_version(
                plugin.descriptor.version,
                requirement.version,
                subject=f"rules plugin {requirement.id}",
            )

    def discover(self, *, include_builtin: bool = True) -> RulesPluginRegistry:
        if include_builtin and "d20" not in self._plugins:
            self.register(BuiltinD20RulesPlugin())
        entry_points = metadata.entry_points().select(group=RULES_PLUGIN_ENTRY_POINT)
        for entry_point in sorted(entry_points, key=lambda item: (item.name, item.value)):
            loaded = entry_point.load()
            candidate = loaded() if isinstance(loaded, type) else loaded
            if not isinstance(candidate, RulesPlugin) and callable(candidate):
                candidate = candidate()
            if not isinstance(candidate, RulesPlugin):
                raise TypeError(
                    f"entry point {entry_point.name} did not provide a RulesPlugin"
                )
            self.register(candidate)
        return self


async def discover_rules_plugins_async(
    *,
    engine_version: str = __version__,
    include_builtin: bool = True,
) -> RulesPluginRegistry:
    registry = RulesPluginRegistry(engine_version=engine_version)
    return await asyncio.to_thread(registry.discover, include_builtin=include_builtin)
