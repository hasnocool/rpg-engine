"""Stable public Python API for rpg-engine 1.x."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import TypeAdapter

from rpg_engine import __version__
from rpg_engine.commands import Command, parse_command
from rpg_engine.content.loader import load_content_pack, load_content_pack_async
from rpg_engine.content.models import ContentRegistry
from rpg_engine.engine import SimulationEngine
from rpg_engine.events import Event, parse_event
from rpg_engine.models import StrictModel, WorldState
from rpg_engine.reducer import apply_event
from rpg_engine.rules.base import RulesRuntime
from rpg_engine.rules.d20 import D20RulesRuntime
from rpg_engine.rules.plugin import RulesPluginDescriptor

ENGINE_API_VERSION = "1.0"
CONTENT_API_VERSION = "1.0"
RULES_API_VERSION = "1"


class PublicContractManifest(StrictModel):
    engine_version: str = __version__
    engine_api: str = ENGINE_API_VERSION
    content_api: str = CONTENT_API_VERSION
    rules_api: str = RULES_API_VERSION
    stability: str = "stable"
    compatibility: str = "Breaking public-contract changes require a new engine major version."


class EngineSession:
    """Small stable facade over the authoritative deterministic engine."""

    def __init__(
        self,
        world: WorldState,
        *,
        content: ContentRegistry | None = None,
        rules: RulesRuntime | None = None,
    ) -> None:
        self._engine = SimulationEngine(
            world,
            content=content or ContentRegistry.with_core_defaults(),
            rules=rules or D20RulesRuntime(),
        )

    @classmethod
    def create(
        cls,
        *,
        seed: int,
        campaign_id: str = "campaign",
        content: ContentRegistry | None = None,
        rules: RulesRuntime | None = None,
    ) -> EngineSession:
        return cls(
            WorldState(campaign_id=campaign_id, seed=seed),
            content=content,
            rules=rules,
        )

    @classmethod
    def replay(
        cls,
        *,
        seed: int,
        campaign_id: str,
        events: Iterable[Event | Mapping[str, Any]],
        content: ContentRegistry | None = None,
        rules: RulesRuntime | None = None,
    ) -> EngineSession:
        world = WorldState(campaign_id=campaign_id, seed=seed)
        for item in events:
            event = item if not isinstance(item, Mapping) else parse_event(dict(item))
            apply_event(world, event)
        return cls(world, content=content, rules=rules)

    @property
    def state(self) -> WorldState:
        return self._engine.world.model_copy(deep=True)

    def execute(self, command: Command | Mapping[str, Any]) -> list[Event]:
        typed = command if not isinstance(command, Mapping) else parse_command(dict(command))
        return self._engine.execute(typed)


def public_contract_manifest() -> PublicContractManifest:
    return PublicContractManifest()


def public_contract_schemas() -> dict[str, object]:
    """Schemas used by public clients, content tooling, and compatibility checks."""

    return {
        "manifest": public_contract_manifest().model_dump(mode="json"),
        "command": TypeAdapter(Command).json_schema(),
        "event": TypeAdapter(Event).json_schema(),
        "world_state": WorldState.model_json_schema(),
        "content_registry": ContentRegistry.model_json_schema(),
        "rules_plugin": RulesPluginDescriptor.model_json_schema(),
    }


__all__ = [
    "CONTENT_API_VERSION",
    "ENGINE_API_VERSION",
    "RULES_API_VERSION",
    "EngineSession",
    "PublicContractManifest",
    "load_content_pack",
    "load_content_pack_async",
    "public_contract_manifest",
    "public_contract_schemas",
]
