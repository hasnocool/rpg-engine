"""Creator-platform linting with schema, graph, dependency, and cross-reference diagnostics."""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict, deque
from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import ValidationError

from rpg_engine.content.models import ContentManifest, ContentRegistry
from rpg_engine.creator.catalog import RESOURCE_SPECS
from rpg_engine.creator.dependencies import resolve_dependencies
from rpg_engine.creator.models import LintIssue, LintReport, LintSeverity
from rpg_engine.creator.workspace import CreatorWorkspace

_RESOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _read_mapping(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("expected a YAML mapping")
    return payload


def _issue(
    issues: list[LintIssue],
    severity: LintSeverity,
    code: str,
    message: str,
    *,
    root: Path,
    path: Path | None = None,
    resource_id: str | None = None,
) -> None:
    issues.append(
        LintIssue(
            severity=severity,
            code=code,
            message=message,
            path=str(path.relative_to(root)) if path is not None else None,
            resource_id=resource_id,
        )
    )


def _lint_dialogue_graph(registry: ContentRegistry, issues: list[LintIssue], root: Path) -> None:
    for dialogue in registry.dialogues.values():
        reachable: set[str] = set()
        queue = deque([dialogue.start_node_id])
        while queue:
            node_id = queue.popleft()
            if node_id in reachable:
                continue
            reachable.add(node_id)
            node = dialogue.nodes[node_id]
            for option in node.options:
                for destination in (
                    option.next_node_id,
                    option.success_node_id,
                    option.failure_node_id,
                ):
                    if destination is not None and destination not in reachable:
                        queue.append(destination)
        unreachable = sorted(set(dialogue.nodes) - reachable)
        if unreachable:
            _issue(
                issues,
                LintSeverity.WARNING,
                "dialogue.unreachable_nodes",
                f"dialogue {dialogue.id} has unreachable nodes: {', '.join(unreachable)}",
                root=root,
                resource_id=dialogue.id,
            )


def _lint_quest_graph(registry: ContentRegistry, issues: list[LintIssue], root: Path) -> None:
    for quest in registry.quests.values():
        outgoing: defaultdict[str, int] = defaultdict(int)
        for transition in quest.transitions:
            outgoing[transition.from_state] += 1
        dead_ends = sorted(
            state
            for state in quest.states
            if state not in quest.terminal_states and outgoing[state] == 0
        )
        if dead_ends:
            _issue(
                issues,
                LintSeverity.WARNING,
                "quest.dead_end_states",
                f"quest {quest.id} has non-terminal dead-end states: {', '.join(dead_ends)}",
                root=root,
                resource_id=quest.id,
            )


def _lint_map_graph(registry: ContentRegistry, issues: list[LintIssue], root: Path) -> None:
    if len(registry.locations) <= 1:
        return
    adjacency: defaultdict[str, set[str]] = defaultdict(set)
    for connection in registry.connections.values():
        adjacency[connection.from_location_id].add(connection.to_location_id)
        if connection.bidirectional:
            adjacency[connection.to_location_id].add(connection.from_location_id)
    start = sorted(registry.locations)[0]
    reachable = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for neighbor in sorted(adjacency[current]):
            if neighbor not in reachable:
                reachable.add(neighbor)
                queue.append(neighbor)
    disconnected = sorted(set(registry.locations) - reachable)
    if disconnected:
        _issue(
            issues,
            LintSeverity.WARNING,
            "map.disconnected_locations",
            f"map has locations disconnected from {start}: {', '.join(disconnected)}",
            root=root,
        )


def _lint_campaigns(
    workspace: CreatorWorkspace,
    registry: ContentRegistry,
    issues: list[LintIssue],
    root: Path,
) -> None:
    try:
        campaigns = workspace.campaign_drafts()
    except (ValidationError, ValueError, KeyError) as exc:
        _issue(
            issues,
            LintSeverity.ERROR,
            "campaign.invalid",
            str(exc),
            root=root,
        )
        return
    for campaign in campaigns:
        if (
            campaign.start_location_id is not None
            and campaign.start_location_id not in registry.locations
        ):
            _issue(
                issues,
                LintSeverity.ERROR,
                "campaign.unknown_start_location",
                f"campaign {campaign.id} references unknown start location "
                f"{campaign.start_location_id}",
                root=root,
                resource_id=campaign.id,
            )
        missing_templates = sorted(
            set(campaign.party_template_ids) - set(registry.npc_templates)
        )
        if missing_templates:
            _issue(
                issues,
                LintSeverity.ERROR,
                "campaign.unknown_party_templates",
                f"campaign {campaign.id} references unknown creature templates: "
                f"{', '.join(missing_templates)}",
                root=root,
                resource_id=campaign.id,
            )


def lint_workspace(
    root: Path | str,
    *,
    available_pack_roots: list[Path] | None = None,
    rules_plugins: Mapping[str, str] | None = None,
) -> LintReport:
    """Lint a creator workspace and return all diagnostics which can be collected safely."""

    root_path = Path(root).resolve()
    workspace = CreatorWorkspace(root_path)
    issues: list[LintIssue] = []
    stats: defaultdict[str, int] = defaultdict(int)

    manifest: ContentManifest | None = None
    try:
        manifest = workspace.manifest()
    except (OSError, ValidationError, ValueError) as exc:
        _issue(
            issues,
            LintSeverity.ERROR,
            "manifest.invalid",
            str(exc),
            root=root_path,
            path=workspace.manifest_path if workspace.manifest_path.exists() else None,
        )

    try:
        workspace.mod_metadata()
    except (OSError, ValidationError, ValueError) as exc:
        _issue(
            issues,
            LintSeverity.ERROR,
            "mod.invalid",
            str(exc),
            root=root_path,
            path=workspace.mod_path if workspace.mod_path.exists() else None,
        )

    resource_errors = False
    for spec in RESOURCE_SPECS:
        directory = root_path / spec.directory
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            stats[spec.kind] += 1
            if not _RESOURCE_ID.fullmatch(path.stem):
                resource_errors = True
                _issue(
                    issues,
                    LintSeverity.ERROR,
                    "resource.invalid_filename",
                    f"invalid resource filename: {path.name}",
                    root=root_path,
                    path=path,
                )
                continue
            try:
                payload = _read_mapping(path)
                model = spec.model.model_validate(payload)
                dumped = model.model_dump(mode="json", exclude_none=True)
                resource_id = str(dumped.get("id", path.stem))
                if resource_id != path.stem:
                    raise ValueError(
                        f"resource id {resource_id!r} does not match filename {path.stem!r}"
                    )
            except (OSError, ValidationError, ValueError) as exc:
                resource_errors = True
                _issue(
                    issues,
                    LintSeverity.ERROR,
                    "resource.invalid",
                    str(exc),
                    root=root_path,
                    path=path,
                    resource_id=path.stem,
                )

    registry: ContentRegistry | None = None
    if not resource_errors and manifest is not None:
        try:
            registry = workspace.load_registry()
        except (OSError, ValidationError, ValueError) as exc:
            _issue(
                issues,
                LintSeverity.ERROR,
                "content.cross_reference",
                str(exc),
                root=root_path,
            )

    if registry is not None:
        _lint_map_graph(registry, issues, root_path)
        _lint_dialogue_graph(registry, issues, root_path)
        _lint_quest_graph(registry, issues, root_path)
        _lint_campaigns(workspace, registry, issues, root_path)

        for location in registry.locations.values():
            if not location.description.strip():
                _issue(
                    issues,
                    LintSeverity.INFO,
                    "location.missing_description",
                    f"location {location.id} has no description",
                    root=root_path,
                    resource_id=location.id,
                )

    if manifest is not None:
        roots = [root_path, *(available_pack_roots or [])]
        try:
            resolution = resolve_dependencies(
                roots,
                requested_ids=[manifest.id],
                rules_plugins=rules_plugins,
            )
            stats["resolved_dependencies"] = max(0, len(resolution.order) - 1)
        except (OSError, ValidationError, ValueError) as exc:
            _issue(
                issues,
                LintSeverity.ERROR,
                "dependencies.invalid",
                str(exc),
                root=root_path,
            )

    stats["errors"] = sum(issue.severity == LintSeverity.ERROR for issue in issues)
    stats["warnings"] = sum(issue.severity == LintSeverity.WARNING for issue in issues)
    stats["info"] = sum(issue.severity == LintSeverity.INFO for issue in issues)
    return LintReport(issues=issues, stats=dict(stats))


async def lint_workspace_async(
    root: Path | str,
    *,
    available_pack_roots: list[Path] | None = None,
    rules_plugins: Mapping[str, str] | None = None,
) -> LintReport:
    """Run filesystem-heavy linting away from an active event loop."""

    return await asyncio.to_thread(
        lint_workspace,
        root,
        available_pack_roots=available_pack_roots,
        rules_plugins=rules_plugins,
    )
