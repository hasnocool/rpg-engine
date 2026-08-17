"""Static smoke checks for the reference Godot adapter bundle."""

from pathlib import Path


def test_godot_47_adapter_bundle_is_present() -> None:
    root = Path("clients/godot/addons/rpg_engine")
    expected = {
        "plugin.cfg",
        "plugin.gd",
        "rpg_api.gd",
        "visual_bridge_2d.gd",
        "visual_bridge_3d.gd",
    }
    assert expected <= {path.name for path in root.iterdir() if path.is_file()}

    api = (root / "rpg_api.gd").read_text(encoding="utf-8")
    assert "/api/v1/campaigns/%s/visual" in api
    assert "/presentation/ws?after=%d" in api

    plugin = (root / "plugin.cfg").read_text(encoding="utf-8")
    assert 'version="0.6.0"' in plugin
