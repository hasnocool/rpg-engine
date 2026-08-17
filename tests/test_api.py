"""FastAPI integration smoke tests."""

from pathlib import Path

from fastapi.testclient import TestClient

from rpg_engine.api.app import create_app


def test_rest_command_round_trip(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "api.db", content_path=Path("content/core"))
    with TestClient(app) as client:
        created = client.post("/campaigns", json={"seed": 101, "campaign_id": "test"})
        assert created.status_code == 200

        command = {
            "type": "create_entity",
            "entity": {
                "id": "hero",
                "identity": {"name": "Hero", "tags": []},
                "stats": {},
                "health": {"current": 12, "maximum": 12},
                "position": {},
                "inventory": {},
                "conditions": [],
                "faction_id": None,
                "ai_profile": None,
            },
        }
        response = client.post("/campaigns/test/commands", json=command)
        assert response.status_code == 200
        assert response.json()["events"][0]["type"] == "entity_created"

        state = client.get("/campaigns/test/state").json()
        assert state["entities"]["hero"]["identity"]["name"] == "Hero"
