"""Shared version-constraint primitives for content packs and rules plugins."""

from __future__ import annotations

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import Field, field_validator

from rpg_engine.models import StrictModel


class VersionRequirement(StrictModel):
    """A PEP 440 compatible dependency requirement.

    ``*`` means any version. Optional requirements do not fail resolution when
    the target package or plugin is absent, but do fail when it is present with
    an incompatible version.
    """

    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    version: str = "*"
    optional: bool = False

    @field_validator("version")
    @classmethod
    def validate_constraint(cls, value: str) -> str:
        if value == "*":
            return value
        try:
            SpecifierSet(value)
        except InvalidSpecifier as exc:
            raise ValueError(f"invalid version constraint: {value}") from exc
        return value


def parsed_version(value: str) -> Version:
    """Parse a version and raise a stable ValueError for authoring diagnostics."""

    try:
        return Version(value)
    except InvalidVersion as exc:
        raise ValueError(f"invalid version: {value}") from exc


def version_satisfies(version: str, constraint: str) -> bool:
    """Return whether ``version`` satisfies a PEP 440 constraint or ``*``."""

    parsed = parsed_version(version)
    if constraint == "*":
        return True
    try:
        return parsed in SpecifierSet(constraint)
    except InvalidSpecifier as exc:
        raise ValueError(f"invalid version constraint: {constraint}") from exc


def require_version(version: str, constraint: str, *, subject: str) -> None:
    """Raise a human-readable error when a version does not satisfy a constraint."""

    if not version_satisfies(version, constraint):
        raise ValueError(f"{subject} version {version} does not satisfy {constraint}")
