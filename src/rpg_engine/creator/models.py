"""Creator-platform authoring models which are not authoritative simulation state."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from rpg_engine.models import Ability, StrictModel
from rpg_engine.versioning import VersionRequirement


class ModMetadata(StrictModel):
    """Optional creator/mod metadata stored in ``mod.yaml`` beside a content manifest."""

    schema_version: int = Field(default=1, ge=1)
    engine: str = ">=0.9,<1.0"
    dependencies: list[VersionRequirement] = Field(default_factory=list)
    rules_plugins: list[VersionRequirement] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_requirements(self) -> ModMetadata:
        for label, requirements in (
            ("dependency", self.dependencies),
            ("rules plugin", self.rules_plugins),
        ):
            ids = [requirement.id for requirement in requirements]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {label} requirement")
        return self


class CampaignDraft(StrictModel):
    """Creator-facing campaign blueprint kept separate from a live save game."""

    id: str
    name: str
    description: str = ""
    seed: int = 918392482
    start_location_id: str | None = None
    party_template_ids: list[str] = Field(default_factory=list)
    tags: set[str] = Field(default_factory=set)


class ItemDocument(StrictModel):
    """Editable item YAML shape, including the loader's optional weapon fields."""

    id: str
    name: str
    value: int = Field(default=0, ge=0)
    weight: float = Field(default=0.0, ge=0)
    tags: set[str] = Field(default_factory=set)
    equip_slot: str | None = None
    effect_id: str | None = None
    ability: Ability | None = None
    damage: str | None = None
    damage_type: str | None = None
    attack_bonus: int | None = None
    damage_bonus: int | None = None
    range: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def normalize_weapon_tag(self) -> ItemDocument:
        if any(
            value is not None
            for value in (
                self.ability,
                self.damage,
                self.damage_type,
                self.attack_bonus,
                self.damage_bonus,
                self.range,
            )
        ):
            self.tags.add("weapon")
        return self


class MapPoint(StrictModel):
    x: float
    y: float


class MapLayout(StrictModel):
    """Creator-only graph layout; logical topology remains in connection resources."""

    positions: dict[str, MapPoint] = Field(default_factory=dict)


class LintSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class LintIssue(StrictModel):
    severity: LintSeverity
    code: str
    message: str
    path: str | None = None
    resource_id: str | None = None


class LintReport(StrictModel):
    valid: bool = True
    issues: list[LintIssue] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def derive_validity(self) -> LintReport:
        object.__setattr__(
            self,
            "valid",
            not any(issue.severity == LintSeverity.ERROR for issue in self.issues),
        )
        return self


class ResourceRecord(StrictModel):
    kind: str
    id: str
    relative_path: str
    name: str | None = None
    payload: dict[str, object] | None = None


class MapNode(StrictModel):
    id: str
    name: str
    region: str | None = None
    x: float | None = None
    y: float | None = None


class MapEdge(StrictModel):
    id: str
    from_location_id: str
    to_location_id: str
    bidirectional: bool
    hidden: bool
    travel_minutes: int


class MapGraph(StrictModel):
    nodes: list[MapNode] = Field(default_factory=list)
    edges: list[MapEdge] = Field(default_factory=list)
