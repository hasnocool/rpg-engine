"""Distribution and marketplace contracts for the v1 RPG platform."""

from __future__ import annotations

from typing import Literal

from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pydantic import Field, model_validator

from rpg_engine.models import StrictModel
from rpg_engine.versioning import VersionRequirement

ReleaseChannel = Literal["stable", "beta", "nightly"]


class ReleaseArtifact(StrictModel):
    platform: str
    arch: str = "any"
    kind: str = "archive"
    url: str
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    size_bytes: int | None = Field(default=None, ge=0)
    content_type: str = "application/octet-stream"


class ClientRelease(StrictModel):
    client_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    name: str
    version: str
    channel: ReleaseChannel = "stable"
    engine: str = ">=1,<2"
    api_version: str = "1.0"
    artifacts: list[ReleaseArtifact] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_versions(self) -> ClientRelease:
        Version(self.version)
        SpecifierSet(self.engine)
        return self


class ContentRelease(StrictModel):
    pack_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    name: str
    version: str
    engine: str = ">=1,<2"
    ruleset: str = "d20"
    download_url: str
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    size_bytes: int | None = Field(default=None, ge=0)
    license: str = "unspecified"
    tags: set[str] = Field(default_factory=set)
    dependencies: list[VersionRequirement] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_versions(self) -> ContentRelease:
        Version(self.version)
        SpecifierSet(self.engine)
        return self


class MarketplaceListing(StrictModel):
    listing_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    pack_id: str
    version: str
    title: str
    summary: str = ""
    publisher: str
    license: str = "unspecified"
    tags: set[str] = Field(default_factory=set)
    price_minor: int | None = Field(default=None, ge=0)
    currency: str | None = None
    external_checkout_url: str | None = None

    @model_validator(mode="after")
    def validate_price(self) -> MarketplaceListing:
        Version(self.version)
        if self.price_minor not in (None, 0) and not self.currency:
            raise ValueError("currency is required for a non-zero marketplace price")
        return self


class ResolvedClient(StrictModel):
    release: ClientRelease
    artifact: ReleaseArtifact


class PlatformInfo(StrictModel):
    engine_version: str
    engine_api: str = "1.0"
    content_api: str = "1.0"
    rules_api: str = "1"
    marketplace_enabled: bool = False
    capabilities: list[str] = Field(default_factory=list)
