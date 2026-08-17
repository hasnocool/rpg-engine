from pathlib import Path

import pytest
import yaml

from rpg_engine.creator.dependencies import resolve_dependencies


def _pack(
    root: Path,
    pack_id: str,
    version: str,
    *,
    dependencies: list[dict[str, object]] | None = None,
    rules_plugins: list[dict[str, object]] | None = None,
    engine: str = ">=0.9,<2.0",
) -> Path:
    root.mkdir()
    (root / "manifest.yaml").write_text(
        yaml.safe_dump(
            {"id": pack_id, "name": pack_id.title(), "version": version, "ruleset": "d20"}
        ),
        encoding="utf-8",
    )
    (root / "mod.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "engine": engine,
                "dependencies": dependencies or [],
                "rules_plugins": rules_plugins or [],
            }
        ),
        encoding="utf-8",
    )
    return root


def test_dependency_resolution_orders_dependencies_first(tmp_path: Path) -> None:
    core = _pack(tmp_path / "core", "core", "0.9.0")
    addon = _pack(
        tmp_path / "addon",
        "addon",
        "1.2.0",
        dependencies=[{"id": "core", "version": ">=0.9,<1.0"}],
    )

    result = resolve_dependencies([addon, core], requested_ids=["addon"])

    assert result.order == ["core", "addon"]
    assert result.roots_in_load_order == [core.resolve(), addon.resolve()]


def test_dependency_resolution_rejects_version_mismatch(tmp_path: Path) -> None:
    core = _pack(tmp_path / "core", "core", "0.8.0")
    addon = _pack(
        tmp_path / "addon",
        "addon",
        "1.0.0",
        dependencies=[{"id": "core", "version": ">=0.9"}],
    )

    with pytest.raises(ValueError, match="does not satisfy"):
        resolve_dependencies([core, addon], requested_ids=["addon"])


def test_dependency_resolution_rejects_cycles(tmp_path: Path) -> None:
    alpha = _pack(
        tmp_path / "alpha",
        "alpha",
        "1.0.0",
        dependencies=[{"id": "beta", "version": "*"}],
    )
    beta = _pack(
        tmp_path / "beta",
        "beta",
        "1.0.0",
        dependencies=[{"id": "alpha", "version": "*"}],
    )

    with pytest.raises(ValueError, match="dependency cycle"):
        resolve_dependencies([alpha, beta], requested_ids=["alpha"])


def test_rules_plugin_requirements_are_checked(tmp_path: Path) -> None:
    addon = _pack(
        tmp_path / "addon",
        "addon",
        "1.0.0",
        rules_plugins=[{"id": "my_rules", "version": ">=2,<3"}],
    )

    with pytest.raises(ValueError, match="requires rules plugin"):
        resolve_dependencies([addon], requested_ids=["addon"])

    resolved = resolve_dependencies(
        [addon],
        requested_ids=["addon"],
        rules_plugins={"my_rules": "2.4.0"},
    )
    assert resolved.order == ["addon"]
