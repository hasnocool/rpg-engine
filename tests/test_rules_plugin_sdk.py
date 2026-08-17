from typing import ClassVar

import pytest

from rpg_engine.rules.d20 import D20RulesRuntime
from rpg_engine.rules.plugin import (
    BuiltinD20RulesPlugin,
    RulesPluginDescriptor,
    RulesPluginRegistry,
)
from rpg_engine.versioning import VersionRequirement


class ExamplePlugin:
    descriptor: ClassVar[RulesPluginDescriptor] = RulesPluginDescriptor(
        id="example",
        name="Example",
        version="1.2.0",
        engine=">=0.9,<1.0",
    )

    def create_runtime(self) -> D20RulesRuntime:
        return D20RulesRuntime()


def test_rules_plugin_registry_validates_and_instantiates() -> None:
    registry = RulesPluginRegistry(engine_version="0.9.0")
    registry.register(BuiltinD20RulesPlugin())
    registry.register(ExamplePlugin())

    assert registry.versions == {"d20": "0.9.0", "example": "1.2.0"}
    assert isinstance(registry.runtime("example"), D20RulesRuntime)
    registry.validate_requirements([VersionRequirement(id="example", version=">=1,<2")])


def test_rules_plugin_registry_rejects_bad_api_and_duplicates() -> None:
    registry = RulesPluginRegistry(engine_version="0.9.0")
    registry.register(ExamplePlugin())

    with pytest.raises(ValueError, match="duplicate"):
        registry.register(ExamplePlugin())

    class BadApiPlugin:
        descriptor: ClassVar[RulesPluginDescriptor] = RulesPluginDescriptor(
            id="bad",
            name="Bad",
            version="1.0.0",
            api_version="99",
            engine=">=0.9,<1.0",
        )

        def create_runtime(self) -> D20RulesRuntime:
            return D20RulesRuntime()

    with pytest.raises(ValueError, match="uses API"):
        registry.register(BadApiPlugin())
