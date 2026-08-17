from pathlib import Path

from fastapi.testclient import TestClient

from rpg_engine.creator.app import create_creator_app
from rpg_engine.creator.workspace import CreatorWorkspace


def test_creator_api_crud_validation_and_map(tmp_path: Path) -> None:
    workspace = CreatorWorkspace(tmp_path / "pack")
    workspace.initialize(pack_id="api_pack", name="API Pack")
    app = create_creator_app(workspace.root)

    with TestClient(app) as client:
        info = client.get("/api/creator/v1/info")
        assert info.status_code == 200
        assert info.json()["pack_id"] == "api_pack"

        created = client.post(
            "/api/creator/v1/resources/location/village/template",
            params={"name": "Village"},
        )
        assert created.status_code == 200

        saved = client.put(
            "/api/creator/v1/resources/location/village",
            json={"id": "village", "name": "Village", "description": "Home."},
        )
        assert saved.status_code == 200
        assert saved.json()["payload"]["description"] == "Home."

        schemas = client.get("/api/creator/v1/schemas")
        assert schemas.status_code == 200
        assert "creature" in schemas.json()["resources"]

        map_response = client.get("/api/creator/v1/map")
        assert map_response.status_code == 200
        assert map_response.json()["graph"]["nodes"][0]["id"] == "village"

        lint = client.post("/api/creator/v1/validate")
        assert lint.status_code == 200
        assert lint.json()["valid"] is True

        ui = client.get("/creator")
        assert ui.status_code == 200
        assert "RPG Engine Creator v0.9" in ui.text
