"""Async event-store and campaign-service tests."""

from pathlib import Path

import pytest

from rpg_engine.commands import AdvanceTimeCommand, CreateEntityCommand
from rpg_engine.models import Entity, Health, Identity
from rpg_engine.persistence.sqlite import SQLiteEventStore
from rpg_engine.service import CampaignService


@pytest.mark.asyncio
async def test_campaign_survives_service_reload(tmp_path: Path) -> None:
    db_path = tmp_path / "campaign.db"
    store = SQLiteEventStore(db_path)
    await store.initialize()
    service = CampaignService(store, snapshot_interval=100)
    await service.create_campaign(777, campaign_id="campaign")
    await service.execute(
        "campaign",
        CreateEntityCommand(
            entity=Entity(
                id="hero",
                identity=Identity(name="Hero"),
                health=Health(current=10, maximum=10),
            )
        ),
    )
    await service.execute("campaign", AdvanceTimeCommand(minutes=45))

    reloaded = CampaignService(SQLiteEventStore(db_path), snapshot_interval=100)
    state = await reloaded.state("campaign")

    assert state.time_minutes == 45
    assert state.entities["hero"].identity.name == "Hero"
    assert state.sequence == 2
