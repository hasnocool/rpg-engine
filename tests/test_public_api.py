from rpg_engine import __version__
from rpg_engine.commands import CreateEntityCommand
from rpg_engine.models import Entity, Identity
from rpg_engine.public import (
    ENGINE_API_VERSION,
    EngineSession,
    public_contract_manifest,
    public_contract_schemas,
)


def test_v1_public_facade_executes_and_replays() -> None:
    session = EngineSession.create(seed=1234, campaign_id="public-test")
    events = session.execute(
        CreateEntityCommand(entity=Entity(id="hero", identity=Identity(name="Hero")))
    )
    assert session.state.entities["hero"].identity.name == "Hero"

    replayed = EngineSession.replay(
        seed=1234,
        campaign_id="public-test",
        events=[event.model_dump(mode="json") for event in events],
    )
    assert replayed.state == session.state


def test_v1_contract_manifest_and_schemas_are_stable() -> None:
    manifest = public_contract_manifest()
    schemas = public_contract_schemas()

    assert __version__ == "1.0.0"
    assert ENGINE_API_VERSION == "1.0"
    assert manifest.engine_api == "1.0"
    assert {"command", "event", "world_state", "content_registry", "rules_plugin"} <= schemas.keys()
