"""YAML content-pack loading with async wrappers for server use."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from rpg_engine.content.models import (
    CalendarSpec,
    ContainerTemplateSpec,
    ContentManifest,
    ContentRegistry,
    DialogueSpec,
    DiscoverySpec,
    DynamicQuestTemplateSpec,
    EffectSpec,
    FactionSpec,
    ItemSpec,
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
from rpg_engine.models import WeaponSpec


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected mapping in {path}")
    return payload


def _load_directory[ModelT: BaseModel](
    root: Path, relative: str, model: type[ModelT]
) -> list[ModelT]:
    directory = root / relative
    if not directory.exists():
        return []
    return [model.model_validate(_read_yaml(path)) for path in sorted(directory.glob("*.yaml"))]


def _item_from_payload(payload: dict[str, Any]) -> ItemSpec:
    tags = set(payload.get("tags", []))
    if "damage" in payload or "ability" in payload or "damage_type" in payload:
        tags.add("weapon")
    equip_slot = payload.get("equip_slot")
    if equip_slot is None and "weapon" in tags:
        equip_slot = "hand"
    return ItemSpec(
        id=str(payload["id"]),
        name=str(payload.get("name", payload["id"])),
        value=int(payload.get("value", 0)),
        weight=float(payload.get("weight", 0.0)),
        tags=tags,
        equip_slot=equip_slot,
        effect_id=payload.get("effect_id"),
    )


def _weapon_from_payload(payload: dict[str, Any]) -> WeaponSpec | None:
    if not any(key in payload for key in ("damage", "ability", "damage_type", "attack_bonus")):
        return None
    allowed = {
        "id",
        "name",
        "ability",
        "damage",
        "damage_type",
        "attack_bonus",
        "damage_bonus",
        "range",
    }
    return WeaponSpec.model_validate(
        {key: value for key, value in payload.items() if key in allowed}
    )


def _store_unique(target: dict[str, Any], item: BaseModel, *, category: str) -> None:
    item_id = str(item.model_dump()["id"])
    if item_id in target:
        raise ValueError(f"duplicate {category} id: {item_id}")
    target[item_id] = item


def _require_ids(
    values: list[str] | set[str],
    available: dict[str, Any],
    *,
    owner: str,
    category: str,
) -> None:
    missing = sorted(set(values) - set(available))
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"{owner} references unknown {category}: {joined}")


def validate_content_registry(registry: ContentRegistry) -> ContentRegistry:
    """Validate cross-file references after every content object has been loaded."""

    for item in registry.items.values():
        if item.effect_id is not None and item.effect_id not in registry.effects:
            raise ValueError(f"item {item.id} references unknown effect: {item.effect_id}")

    for container in registry.containers.values():
        if container.location_id is not None and container.location_id not in registry.locations:
            raise ValueError(
                f"container {container.id} references unknown location: {container.location_id}"
            )
        _require_ids(
            container.item_ids,
            registry.items,
            owner=f"container {container.id}",
            category="items",
        )
        if any(amount < 0 for amount in container.currency.values()):
            raise ValueError(f"container {container.id} has negative currency")

    for connection in registry.connections.values():
        _require_ids(
            [connection.from_location_id, connection.to_location_id],
            registry.locations,
            owner=f"connection {connection.id}",
            category="locations",
        )

    for discovery in registry.discoveries.values():
        _require_ids(
            [discovery.location_id, *discovery.reveal_location_ids],
            registry.locations,
            owner=f"discovery {discovery.id}",
            category="locations",
        )
        _require_ids(
            discovery.reveal_connection_ids,
            registry.connections,
            owner=f"discovery {discovery.id}",
            category="connections",
        )
        _require_ids(
            discovery.reveal_container_ids,
            registry.containers,
            owner=f"discovery {discovery.id}",
            category="containers",
        )

    for merchant in registry.merchants.values():
        _require_ids(
            merchant.stock_item_ids,
            registry.items,
            owner=f"merchant {merchant.id}",
            category="items",
        )
        _require_ids(
            set(merchant.price_overrides),
            registry.items,
            owner=f"merchant {merchant.id}",
            category="price override items",
        )

    for template in registry.npc_templates.values():
        if template.dialogue_id is not None and template.dialogue_id not in registry.dialogues:
            raise ValueError(
                f"NPC template {template.id} references unknown dialogue: {template.dialogue_id}"
            )
        if template.merchant_id is not None and template.merchant_id not in registry.merchants:
            raise ValueError(
                f"NPC template {template.id} references unknown merchant: {template.merchant_id}"
            )
        if template.schedule_id is not None and template.schedule_id not in registry.npc_schedules:
            raise ValueError(
                f"NPC template {template.id} references unknown schedule: {template.schedule_id}"
            )

    for dialogue in registry.dialogues.values():
        for node_key, node in dialogue.nodes.items():
            if node_key != node.id:
                raise ValueError(
                    f"dialogue {dialogue.id} node key {node_key!r} does not match id {node.id!r}"
                )
            for option in node.options:
                destinations = {
                    destination
                    for destination in (
                        option.next_node_id,
                        option.success_node_id,
                        option.failure_node_id,
                    )
                    if destination is not None
                }
                _require_ids(
                    destinations,
                    dialogue.nodes,
                    owner=f"dialogue {dialogue.id} option {option.id}",
                    category="nodes",
                )
                for quest_id, allowed_states in option.requires_quest_states.items():
                    quest = registry.quests.get(quest_id)
                    if quest is None:
                        raise ValueError(
                            f"dialogue {dialogue.id} option {option.id} references unknown "
                            f"quest: {quest_id}"
                        )
                    unknown_states = sorted(allowed_states - quest.states)
                    if unknown_states:
                        joined = ", ".join(unknown_states)
                        raise ValueError(
                            f"dialogue {dialogue.id} option {option.id} references unknown "
                            f"quest states for {quest_id}: {joined}"
                        )
                for action in option.quest_actions:
                    quest = registry.quests.get(action.quest_id)
                    if quest is None:
                        raise ValueError(
                            f"dialogue {dialogue.id} option {option.id} references unknown "
                            f"quest action: {action.quest_id}"
                        )
                    if action.type == "trigger":
                        assert action.trigger is not None
                        if not any(
                            transition.trigger == action.trigger for transition in quest.transitions
                        ):
                            raise ValueError(
                                f"dialogue {dialogue.id} option {option.id} references unknown "
                                f"quest trigger {action.trigger!r} for {action.quest_id}"
                            )

    for schedule in registry.npc_schedules.values():
        _require_ids(
            [entry.location_id for entry in schedule.entries],
            registry.locations,
            owner=f"NPC schedule {schedule.id}",
            category="locations",
        )

    for faction in registry.factions.values():
        _require_ids(
            set(faction.base_relations),
            registry.factions,
            owner=f"faction {faction.id}",
            category="factions",
        )
        if faction.id in faction.base_relations:
            raise ValueError(f"faction {faction.id} cannot define a relation with itself")
        for other_id, value in faction.base_relations.items():
            reciprocal = registry.factions[other_id].base_relations.get(faction.id)
            if reciprocal is not None and reciprocal != value:
                raise ValueError(
                    f"faction relation mismatch: {faction.id}/{other_id} "
                    f"declares {value} and {reciprocal}"
                )

    for settlement in registry.settlements.values():
        _require_ids(
            [settlement.location_id],
            registry.locations,
            owner=f"settlement {settlement.id}",
            category="locations",
        )
        if settlement.faction_id is not None:
            _require_ids(
                [settlement.faction_id],
                registry.factions,
                owner=f"settlement {settlement.id}",
                category="factions",
            )

    regions = {location.region for location in registry.locations.values() if location.region}
    for profile in registry.weather_profiles.values():
        if profile.region_id not in regions:
            raise ValueError(
                f"weather profile {profile.id} references unknown region: {profile.region_id}"
            )

    for template in registry.dynamic_quest_templates.values():
        _require_ids(
            template.target_location_ids,
            registry.locations,
            owner=f"dynamic quest template {template.id}",
            category="locations",
        )

    for rumor in registry.rumor_templates.values():
        _require_ids(
            [rumor.location_id],
            registry.locations,
            owner=f"rumor {rumor.id}",
            category="locations",
        )
        if (
            rumor.quest_template_id is not None
            and rumor.quest_template_id not in registry.dynamic_quest_templates
        ):
            raise ValueError(
                f"rumor {rumor.id} references unknown dynamic quest template: "
                f"{rumor.quest_template_id}"
            )

    for node in registry.resource_nodes.values():
        _require_ids(
            [node.location_id],
            registry.locations,
            owner=f"resource node {node.id}",
            category="locations",
        )
        _require_ids(
            [node.item_id],
            registry.items,
            owner=f"resource node {node.id}",
            category="items",
        )

    return registry


def load_content_pack(root: Path) -> ContentRegistry:
    registry = ContentRegistry.with_core_defaults()
    manifest_path = root / "manifest.yaml"
    if manifest_path.exists():
        registry.manifest = ContentManifest.model_validate(_read_yaml(manifest_path))

    items_dir = root / "items"
    if items_dir.exists():
        for path in sorted(items_dir.glob("*.yaml")):
            payload = _read_yaml(path)
            item = _item_from_payload(payload)
            _store_unique(registry.items, item, category="item")
            weapon = _weapon_from_payload(payload)
            if weapon is not None:
                _store_unique(registry.weapons, weapon, category="weapon")

    for effect in _load_directory(root, "effects", EffectSpec):
        _store_unique(registry.effects, effect, category="effect")
    for template in _load_directory(root, "containers", ContainerTemplateSpec):
        _store_unique(registry.containers, template, category="container")
    for template in _load_directory(root, "npcs", NpcTemplateSpec):
        _store_unique(registry.npc_templates, template, category="NPC template")
    for dialogue in _load_directory(root, "dialogue", DialogueSpec):
        _store_unique(registry.dialogues, dialogue, category="dialogue")
    for quest in _load_directory(root, "quests", QuestSpec):
        _store_unique(registry.quests, quest, category="quest")
    for merchant in _load_directory(root, "merchants", MerchantSpec):
        _store_unique(registry.merchants, merchant, category="merchant")
    for location in _load_directory(root, "world/locations", WorldLocationSpec):
        _store_unique(registry.locations, location, category="location")
    for connection in _load_directory(root, "world/connections", WorldConnectionSpec):
        _store_unique(registry.connections, connection, category="connection")
    for discovery in _load_directory(root, "world/discoveries", DiscoverySpec):
        _store_unique(registry.discoveries, discovery, category="discovery")
    for calendar in _load_directory(root, "world/calendars", CalendarSpec):
        _store_unique(registry.calendars, calendar, category="calendar")
    for profile in _load_directory(root, "weather", WeatherProfileSpec):
        _store_unique(registry.weather_profiles, profile, category="weather profile")
    for schedule in _load_directory(root, "schedules", NpcScheduleSpec):
        _store_unique(registry.npc_schedules, schedule, category="NPC schedule")
    for faction in _load_directory(root, "factions", FactionSpec):
        _store_unique(registry.factions, faction, category="faction")
    for settlement in _load_directory(root, "settlements", SettlementSpec):
        _store_unique(registry.settlements, settlement, category="settlement")
    for template in _load_directory(root, "dynamic_quests", DynamicQuestTemplateSpec):
        _store_unique(
            registry.dynamic_quest_templates, template, category="dynamic quest template"
        )
    for rumor in _load_directory(root, "rumors", RumorTemplateSpec):
        _store_unique(registry.rumor_templates, rumor, category="rumor")
    for node in _load_directory(root, "ecology", ResourceNodeSpec):
        _store_unique(registry.resource_nodes, node, category="resource node")
    return validate_content_registry(registry)


async def load_content_pack_async(root: Path) -> ContentRegistry:
    """Load content without blocking an active event loop."""

    return await asyncio.to_thread(load_content_pack, root)