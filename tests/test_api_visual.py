"""v0.6 visual and presentation API regressions."""

from pathlib import Path

from fastapi.testclient import TestClient

from rpg_engine.api.app import create_app


def test_visual_snapshot_and_presentation_endpoints(tmp_path: Path) -> None:
    app = create_app(
        database_path=tmp_path / "visual.db",
        content_path=Path("content/core"),
        visual_bindings_path=Path("clients/godot/bindings.example.yaml"),
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/campaigns",
            json={"seed": 101, "campaign_id": "visual"},
        )
        assert created.status_code == 200

        create_entity = {
            "type": "create_entity",
            "entity": {
                "id": "hero",
                "identity": {"name": "Hero", "tags": ["hero"]},
                "stats": {},
                "health": {"current": 12, "maximum": 12},
                "position": {"area": "village", "x": 1, "y": 2},
                "inventory": {},
                "conditions": [],
                "resources": {},
                "damage_profile": {},
                "concentration": None,
                "faction_id": None,
                "ai_profile": None,
            },
        }
        response = client.post("/api/v1/campaigns/visual/commands", json=create_entity)
        assert response.status_code == 200
        cursor = response.json()["to_sequence"]

        visual = client.get(
            "/api/v1/campaigns/visual/visual",
            params={"actor_id": "hero"},
        )
        assert visual.status_code == 200
        payload = visual.json()["visual"]
        assert payload["scene_2d"] == "res://world/village_2d.tscn"
        assert payload["actors"][0]["terminal_glyph"] == "@"

        moved = client.post(
            "/api/v1/campaigns/visual/commands",
            json={
                "type": "move_actor",
                "actor_id": "hero",
                "position": {"area": "village", "x": 3, "y": 4},
            },
        )
        assert moved.status_code == 200

        presentation = client.get(
            "/api/v1/campaigns/visual/presentation",
            params={"after": cursor},
        )
        assert presentation.status_code == 200
        batches = presentation.json()["batches"]
        assert batches[-1]["event_type"] == "actor_moved"
        assert batches[-1]["hints"][0]["type"] == "movement_interpolation"
