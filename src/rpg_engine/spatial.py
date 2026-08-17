"""Renderer-neutral spatial and targeting contracts."""

from __future__ import annotations

import heapq
import math
from enum import StrEnum
from typing import Protocol

from pydantic import Field

from rpg_engine.models import Entity, Position, StrictModel


class TargetShape(StrEnum):
    SINGLE = "single"
    RADIUS = "radius"
    LINE = "line"
    CONE = "cone"


class TargetingContract(StrictModel):
    shape: TargetShape = TargetShape.SINGLE
    max_range: float | None = Field(default=None, ge=0)
    radius: float | None = Field(default=None, ge=0)
    max_targets: int | None = Field(default=None, ge=1)
    requires_line_of_sight: bool = False
    include_source: bool = False


class SpatialAdapter(Protocol):
    """Authority-side spatial queries; implementations know no rendering details."""

    def movement_cost(self, start: Position, end: Position) -> int: ...

    def can_target(
        self, source: Position, target: Position, contract: TargetingContract
    ) -> bool: ...

    def targets_in_area(
        self,
        origin: Position,
        entities: list[Entity],
        contract: TargetingContract,
    ) -> list[str]: ...


class GridSpatialAdapter:
    """Coordinate adapter using Euclidean distance in logical world units."""

    @staticmethod
    def _same_space(left: Position, right: Position) -> bool:
        return (
            left.world == right.world
            and left.region == right.region
            and left.area == right.area
            and left.scene == right.scene
        )

    @classmethod
    def distance(cls, left: Position, right: Position) -> float:
        if not cls._same_space(left, right):
            return math.inf
        if left.x is None or left.y is None or right.x is None or right.y is None:
            return 0.0 if left.zone == right.zone else math.inf
        lz = left.z or 0.0
        rz = right.z or 0.0
        return math.dist((left.x, left.y, lz), (right.x, right.y, rz))

    def movement_cost(self, start: Position, end: Position) -> int:
        distance = self.distance(start, end)
        if math.isinf(distance):
            raise ValueError("positions are not connected in this spatial adapter")
        return math.ceil(distance)

    def can_target(
        self, source: Position, target: Position, contract: TargetingContract
    ) -> bool:
        distance = self.distance(source, target)
        return contract.max_range is None or distance <= contract.max_range

    def targets_in_area(
        self,
        origin: Position,
        entities: list[Entity],
        contract: TargetingContract,
    ) -> list[str]:
        if contract.shape == TargetShape.SINGLE:
            raise ValueError("single-target contracts do not define an area")
        radius = contract.radius if contract.radius is not None else contract.max_range
        if radius is None:
            raise ValueError("area targeting requires radius or max_range")
        selected = [
            entity.id
            for entity in sorted(entities, key=lambda item: item.id)
            if self.distance(origin, entity.position) <= radius
        ]
        if contract.max_targets is not None:
            selected = selected[: contract.max_targets]
        return selected


class GraphSpatialAdapter:
    """Weighted graph adapter using ``Position.zone`` as the logical node id."""

    def __init__(self, adjacency: dict[str, dict[str, int]]) -> None:
        self._adjacency = adjacency

    def _distance(self, start: Position, end: Position) -> float:
        if start.world != end.world or start.zone is None or end.zone is None:
            return math.inf
        if start.zone == end.zone:
            return 0.0
        queue: list[tuple[int, str]] = [(0, start.zone)]
        best: dict[str, int] = {start.zone: 0}
        while queue:
            cost, node = heapq.heappop(queue)
            if node == end.zone:
                return float(cost)
            if cost != best[node]:
                continue
            for neighbor, edge_cost in sorted(self._adjacency.get(node, {}).items()):
                candidate = cost + edge_cost
                if candidate < best.get(neighbor, 2**63 - 1):
                    best[neighbor] = candidate
                    heapq.heappush(queue, (candidate, neighbor))
        return math.inf

    def movement_cost(self, start: Position, end: Position) -> int:
        distance = self._distance(start, end)
        if math.isinf(distance):
            raise ValueError("no graph path between positions")
        return int(distance)

    def can_target(
        self, source: Position, target: Position, contract: TargetingContract
    ) -> bool:
        distance = self._distance(source, target)
        return contract.max_range is None or distance <= contract.max_range

    def targets_in_area(
        self,
        origin: Position,
        entities: list[Entity],
        contract: TargetingContract,
    ) -> list[str]:
        radius = contract.radius if contract.radius is not None else contract.max_range
        if radius is None:
            raise ValueError("area targeting requires radius or max_range")
        selected = [
            entity.id
            for entity in sorted(entities, key=lambda item: item.id)
            if self._distance(origin, entity.position) <= radius
        ]
        if contract.max_targets is not None:
            selected = selected[: contract.max_targets]
        return selected
