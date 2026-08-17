"""Stable v1 REST/browser contract tests."""

from pathlib import Path

from fastapi.testclient import TestClient

from rpg_engine.api.app import create_app


def test_v1_contract_and_browser_client(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "api.db", content_path=Path("content/core"))
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/campaigns",
            json={"seed": 101, "campaign_id": "test"},
        )
        assert created.status_code == 200
        assert created.json()["api_version"] == "v1"
        assert created.json()["state"]["campaign_id"] == "test"

        observation = client.get("/api/v1/campaigns/test/observation")
        assert observation.status_code == 200
        assert observation.json()["observation"]["sequence"] == 0

        browser = client.get("/client")
        assert browser.status_code == 200
        assert "resumable WebSocket" in browser.text

        schema = client.get("/openapi.json").json()
        assert "/api/v1/campaigns/{campaign_id}/observation" in schema["paths"]


def test_v1_websocket_replays_after_cursor(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "ws.db", content_path=Path("content/core"))
    with TestClient(app) as client:
        client.post("/api/v1/campaigns", json={"seed": 1, "campaign_id": "test"})
        response = client.post(
            "/api/v1/campaigns/test/commands",
            json={"type": "advance_time", "minutes": 5},
        )
        sequence = response.json()["to_sequence"]

        with client.websocket_connect("/api/v1/campaigns/test/events/ws?after=0") as websocket:
            payload = websocket.receive_json()
            assert payload["events"]
            assert payload["to_sequence"] == sequence
