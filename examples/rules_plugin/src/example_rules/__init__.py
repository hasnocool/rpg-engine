"""Minimal v1 rules-plugin example."""

from typing import ClassVar

from rpg_engine.rules.d20 import D20RulesRuntime
from rpg_engine.rules.plugin import RulesPluginDescriptor


class ExampleRulesPlugin:
    descriptor: ClassVar[RulesPluginDescriptor] = RulesPluginDescriptor(
        id="example_rules",
        name="Example Rules",
        version="1.0.0",
        engine=">=1,<2",
        description="Small reference plugin using the built-in d20 behavior.",
    )

    def create_runtime(self) -> D20RulesRuntime:
        return D20RulesRuntime()


plugin = ExampleRulesPlugin()
