"""v0.5 observation, terminal, and resumable event-stream tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from rpg_engine.commands import AdvanceTimeCommand, CreateEntityCommand, TravelCommand
from rpg_engine.content.models import ContentRegistry, WorldConnectionSpec, WorldLocationSpec
from rpg_engine.models import AdventureKnowledge, Entity, Identity, Position, WorldState
from rpg_engine.observations import build_observation
from rpg_engine.persistence.sqlite import SQLiteEventStore
from rpg_engine.service import CampaignService
from rpg_engine.terminal import parse_terminal_command


def test_observation_hides_unknown_connections() -> None:
    content = ContentRegistry(
        locations={
            "village": WorldLocationSpec(id="village", name="Village"),
            "forest": WorldLocationSpec(id="forest", name="Forest"),
            "ruins": WorldLocationSpec(id="ruins", name="Ruins"),
        },
        connections={
            "road": WorldConnectionSpec(
                id="road",
                from_location_id="village",
                to_location_id="forest",
                travel_minutes=15,
            ),
            "secret": WorldConnectionSpec(
                id="secret",
                from_location_id="village",
                to_location_id="ruins",
                travel_minutes=5,
                hidden=True,
            ),
        },
    )
    world = WorldState(
        campaign_id="test",
        seed=1,
        entities={
            "hero": Entity(
                id="hero",
                identity=Identity(name="Hero"),
                position=Position(area="village"),
            )
        },
        knowledge={"hero": AdventureKnowledge(location_ids={"village"})},
    )

    observation = build_observation(world, content, viewer_id="hero")
    assert observation.location is not None
    assert [exit_.connection_id for exit_ in observation.location.exits] == ["road"]

    world.knowledge["hero"].connection_ids.add("secret")
    observation = build_observation(world, content, viewer_id="hero")
    assert observation.location is not None
    assert [exit_.connection_id for exit_ in observation.location.exits] == ["road", "secret"]


def test_terminal_shortcut_delegates_to_command_schema() -> None:
    command = parse_terminal_command("travel hero forest")
    assert isinstance(command, TravelCommand)
    assert command.actor_id == "hero"
    assert command.destination_id == "forest"


@pytest.mark.asyncio
async def test_event_stream_resumes_from_persisted_cursor(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "stream.db")
    await store.initialize()
    service = CampaignService(store)
    await service.create_campaign(99, campaign_id="campaign")
    first = await service.execute(
        "campaign",
        CreateEntityCommand(entity=Entity(id="hero", identity=Identity(name="Hero"))),
    )
    assert first

    stream = service.stream_events(
        "campaign",
        after_sequence=first[-1].sequence,
        heartbeat_seconds=5.0,
    )
    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    second = await service.execute("campaign", AdvanceTimeCommand(minutes=5))
    resumed = await asyncio.wait_for(pending, timeout=2.0)
    await stream.aclose()

    assert [event.sequence for event in resumed] == [event.sequence for event in second]


@pytest.mark.asyncio
async def test_ssh_listener_uses_key_auth_and_rpg_process_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typing import cast

    import asyncssh

    from rpg_engine.service import CampaignService
    from rpg_engine.ssh_server import SSHServerConfig, create_ssh_listener

    captured: dict[str, object] = {}
    sentinel = object()

    async def fake_listen(host: str, port: int, **kwargs: object) -> object:
        captured.update({"host": host, "port": port, **kwargs})
        return sentinel

    monkeypatch.setattr(asyncssh, "listen", fake_listen)
    service = cast(CampaignService, object())
    result = await create_ssh_listener(
        service,
        SSHServerConfig(
            host="127.0.0.1",
            port=8022,
            host_key=Path("host_key"),
            authorized_keys=Path("authorized_keys"),
        ),
    )

    assert result is sentinel
    assert captured["authorized_client_keys"] == "authorized_keys"
    assert captured["server_host_keys"] == ["host_key"]
    assert callable(captured["process_factory"])
