from pathlib import Path

from rpg_engine.creator.schema import schema_for_kind, schema_index, write_schema_bundle


def test_schema_catalog_exposes_editor_types(tmp_path: Path) -> None:
    index = schema_index()

    assert index["schema_bundle_version"] == 1
    assert {"campaign", "location", "connection", "creature", "item", "effect"} <= set(
        index["resources"]
    )
    assert schema_for_kind("npc")["title"] == "Creature / NPC"

    written = write_schema_bundle(tmp_path)
    assert (tmp_path / "index.json") in written
    assert (tmp_path / "creature.schema.json").is_file()
