from pathlib import Path

import pytest

from rpg_engine.creator.lint import lint_workspace
from rpg_engine.creator.models import MapLayout, MapPoint
from rpg_engine.creator.workspace import CreatorWorkspace


def test_workspace_crud_map_campaign_and_lint(tmp_path: Path) -> None:
    workspace = CreatorWorkspace(tmp_path / "pack")
    workspace.initialize(pack_id="creator_test", name="Creator Test")

    workspace.put(
        "location",
        "village",
        {"id": "village", "name": "Village", "description": "A small village."},
    )
    workspace.put(
        "location",
        "forest",
        {"id": "forest", "name": "Forest", "description": "A dark forest."},
    )
    workspace.connect_locations(
        "village_forest",
        from_location_id="village",
        to_location_id="forest",
        travel_minutes=20,
    )
    workspace.put(
        "effect",
        "minor_heal",
        {
            "id": "minor_heal",
            "name": "Minor Heal",
            "operations": [{"type": "heal", "amount": "1d4"}],
        },
    )
    workspace.put(
        "item",
        "potion",
        {
            "id": "potion",
            "name": "Potion",
            "value": 10,
            "tags": ["consumable"],
            "effect_id": "minor_heal",
        },
    )
    workspace.put(
        "creature",
        "hero_template",
        {
            "id": "hero_template",
            "entity": {
                "id": "hero_template",
                "identity": {"name": "Hero", "tags": ["hero"]},
                "health": {"current": 12, "maximum": 12},
                "position": {"area": "village"},
            },
        },
    )
    workspace.put(
        "campaign",
        "demo_campaign",
        {
            "id": "demo_campaign",
            "name": "Demo Campaign",
            "start_location_id": "village",
            "party_template_ids": ["hero_template"],
        },
    )
    workspace.save_map_layout(
        MapLayout(
            positions={
                "village": MapPoint(x=100, y=100),
                "forest": MapPoint(x=300, y=100),
            }
        )
    )

    graph = workspace.map_graph()
    assert [node.id for node in graph.nodes] == ["forest", "village"]
    assert graph.edges[0].id == "village_forest"
    assert workspace.get("item", "potion").payload["effect_id"] == "minor_heal"
    assert workspace.load_registry().items["potion"].effect_id == "minor_heal"

    report = lint_workspace(workspace.root)
    assert report.valid, [issue.model_dump() for issue in report.issues]


def test_workspace_rejects_path_traversal_ids(tmp_path: Path) -> None:
    workspace = CreatorWorkspace(tmp_path / "pack")
    workspace.initialize(pack_id="safe_pack", name="Safe Pack")

    with pytest.raises(ValueError, match="resource ids"):
        workspace.create_template("item", "../outside")


def test_template_creation_is_schema_valid(tmp_path: Path) -> None:
    workspace = CreatorWorkspace(tmp_path / "pack")
    workspace.initialize(pack_id="templates", name="Templates")
    record = workspace.create_template("creature", "goblin", name="Goblin")

    assert record.kind == "creature"
    assert record.payload["entity"]["identity"]["name"] == "Goblin"
