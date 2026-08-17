from rpg_engine import __version__
from rpg_engine.creator.workspace import CreatorWorkspace
from rpg_engine.multiplayer import HostedCampaignService
from rpg_engine.observations import CampaignObservation
from rpg_engine.public import EngineSession
from rpg_engine.rules.plugin import BuiltinD20RulesPlugin, RulesPluginRegistry
from rpg_engine.service import CampaignService
from rpg_engine.visuals import VisualSnapshot


def test_v1_converges_major_platform_tracks(tmp_path) -> None:
    assert __version__ == "1.0.2"
    assert HostedCampaignService is not None
    assert CampaignObservation is not None
    assert VisualSnapshot is not None
    assert EngineSession is not None
    assert hasattr(CampaignService, "observation")
    assert hasattr(CampaignService, "visual")
    assert hasattr(CampaignService, "stream_events")

    workspace = CreatorWorkspace(tmp_path / "pack")
    workspace.initialize(pack_id="v1-pack", name="V1 Pack")
    assert workspace.mod_metadata().engine == ">=1,<2"

    registry = RulesPluginRegistry()
    registry.register(BuiltinD20RulesPlugin())
    assert registry.versions["d20"] == "1.0.0"
