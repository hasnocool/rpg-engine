"""Canonical creator resource catalog and safe starter templates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from rpg_engine.content.models import (
    CalendarSpec,
    ContainerTemplateSpec,
    DialogueSpec,
    DiscoverySpec,
    DynamicQuestTemplateSpec,
    EffectSpec,
    FactionSpec,
    MerchantSpec,
    NpcScheduleSpec,
    NpcTemplateSpec,
    QuestSpec,
    ResourceNodeSpec,
    RumorTemplateSpec,
    SettlementSpec,
    WeatherProfileSpec,
    WorldConnectionSpec,
    WorldLocationSpec,
)
from rpg_engine.creator.models import CampaignDraft, ItemDocument

TemplateFactory = Callable[[str, str], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class CreatorResourceSpec:
    kind: str
    directory: str
    model: type[BaseModel]
    title: str
    template: TemplateFactory
    aliases: tuple[str, ...] = ()


def _campaign(resource_id: str, name: str) -> dict[str, Any]:
    return {"id": resource_id, "name": name}


def _location(resource_id: str, name: str) -> dict[str, Any]:
    return {"id": resource_id, "name": name, "description": ""}


def _connection(resource_id: str, name: str) -> dict[str, Any]:
    del name
    return {
        "id": resource_id,
        "from_location_id": "location_a",
        "to_location_id": "location_b",
        "travel_minutes": 10,
        "bidirectional": True,
        "hidden": False,
    }


def _creature(resource_id: str, name: str) -> dict[str, Any]:
    return {
        "id": resource_id,
        "entity": {
            "id": resource_id,
            "identity": {"name": name, "tags": ["creature"]},
            "health": {"current": 10, "maximum": 10},
        },
    }


def _item(resource_id: str, name: str) -> dict[str, Any]:
    return {"id": resource_id, "name": name, "value": 0, "weight": 0.0, "tags": []}


def _effect(resource_id: str, name: str) -> dict[str, Any]:
    return {"id": resource_id, "name": name, "operations": []}


def _container(resource_id: str, name: str) -> dict[str, Any]:
    return {"id": resource_id, "name": name, "item_ids": [], "currency": {}}


def _discovery(resource_id: str, name: str) -> dict[str, Any]:
    return {
        "id": resource_id,
        "location_id": "location_a",
        "name": name,
        "dc": 10,
    }


def _dialogue(resource_id: str, name: str) -> dict[str, Any]:
    return {
        "id": resource_id,
        "start_node_id": "start",
        "nodes": {
            "start": {
                "id": "start",
                "text": f"{name} dialogue",
                "options": [],
            }
        },
    }


def _quest(resource_id: str, name: str) -> dict[str, Any]:
    return {
        "id": resource_id,
        "name": name,
        "initial_state": "offered",
        "states": ["offered", "complete"],
        "terminal_states": ["complete"],
        "transitions": [
            {"from_state": "offered", "trigger": "complete", "to_state": "complete"}
        ],
    }


def _merchant(resource_id: str, name: str) -> dict[str, Any]:
    del name
    return {"id": resource_id, "currency": "gold", "stock_item_ids": [], "funds": 0}


def _calendar(resource_id: str, name: str) -> dict[str, Any]:
    del name
    return {"id": resource_id}


def _weather(resource_id: str, name: str) -> dict[str, Any]:
    del name
    return {
        "id": resource_id,
        "region_id": "default",
        "options": [{"condition": "clear", "weight": 1}],
    }


def _schedule(resource_id: str, name: str) -> dict[str, Any]:
    del name
    return {
        "id": resource_id,
        "entries": [{"start_minute": 0, "location_id": "location_a", "activity": "idle"}],
    }


def _faction(resource_id: str, name: str) -> dict[str, Any]:
    return {"id": resource_id, "name": name, "base_relations": {}}


def _settlement(resource_id: str, name: str) -> dict[str, Any]:
    return {"id": resource_id, "name": name, "location_id": "location_a"}


def _dynamic_quest(resource_id: str, name: str) -> dict[str, Any]:
    return {
        "id": resource_id,
        "title": name,
        "description": "",
        "target_location_ids": ["location_a"],
    }


def _rumor(resource_id: str, name: str) -> dict[str, Any]:
    return {"id": resource_id, "text": name, "location_id": "location_a"}


def _resource_node(resource_id: str, name: str) -> dict[str, Any]:
    del name
    return {
        "id": resource_id,
        "location_id": "location_a",
        "item_id": "resource_item",
        "capacity": 10,
        "initial_amount": 10,
    }


RESOURCE_SPECS: tuple[CreatorResourceSpec, ...] = (
    CreatorResourceSpec("campaign", "campaigns", CampaignDraft, "Campaign", _campaign),
    CreatorResourceSpec(
        "location",
        "world/locations",
        WorldLocationSpec,
        "Map location",
        _location,
        aliases=("map", "map_location"),
    ),
    CreatorResourceSpec(
        "connection",
        "world/connections",
        WorldConnectionSpec,
        "Map connection",
        _connection,
        aliases=("edge", "map_connection"),
    ),
    CreatorResourceSpec(
        "creature",
        "npcs",
        NpcTemplateSpec,
        "Creature / NPC",
        _creature,
        aliases=("npc",),
    ),
    CreatorResourceSpec("item", "items", ItemDocument, "Item / weapon", _item),
    CreatorResourceSpec("effect", "effects", EffectSpec, "Effect", _effect),
    CreatorResourceSpec(
        "container", "containers", ContainerTemplateSpec, "Container", _container
    ),
    CreatorResourceSpec("discovery", "world/discoveries", DiscoverySpec, "Discovery", _discovery),
    CreatorResourceSpec("dialogue", "dialogue", DialogueSpec, "Dialogue", _dialogue),
    CreatorResourceSpec("quest", "quests", QuestSpec, "Quest", _quest),
    CreatorResourceSpec("merchant", "merchants", MerchantSpec, "Merchant", _merchant),
    CreatorResourceSpec("calendar", "world/calendars", CalendarSpec, "Calendar", _calendar),
    CreatorResourceSpec("weather", "weather", WeatherProfileSpec, "Weather", _weather),
    CreatorResourceSpec(
        "schedule", "schedules", NpcScheduleSpec, "NPC schedule", _schedule
    ),
    CreatorResourceSpec("faction", "factions", FactionSpec, "Faction", _faction),
    CreatorResourceSpec(
        "settlement", "settlements", SettlementSpec, "Settlement", _settlement
    ),
    CreatorResourceSpec(
        "dynamic_quest",
        "dynamic_quests",
        DynamicQuestTemplateSpec,
        "Dynamic quest template",
        _dynamic_quest,
    ),
    CreatorResourceSpec("rumor", "rumors", RumorTemplateSpec, "Rumor", _rumor),
    CreatorResourceSpec(
        "resource_node", "ecology", ResourceNodeSpec, "Resource node", _resource_node
    ),
)

_BY_KIND = {spec.kind: spec for spec in RESOURCE_SPECS}
for _spec in RESOURCE_SPECS:
    for _alias in _spec.aliases:
        _BY_KIND[_alias] = _spec


def resource_spec(kind: str) -> CreatorResourceSpec:
    """Resolve a canonical creator resource kind or alias."""

    normalized = kind.strip().lower().replace("-", "_")
    try:
        return _BY_KIND[normalized]
    except KeyError as exc:
        supported = ", ".join(spec.kind for spec in RESOURCE_SPECS)
        raise ValueError(
            f"unknown creator resource kind {kind!r}; expected one of: {supported}"
        ) from exc


def canonical_kinds() -> list[str]:
    return [spec.kind for spec in RESOURCE_SPECS]
