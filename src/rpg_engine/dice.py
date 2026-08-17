"""Deterministic named random streams and dice expressions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_DICE_RE = re.compile(r"^(?P<count>\d*)d(?P<sides>\d+)(?P<modifier>[+-]\d+)?$")


@dataclass(frozen=True, slots=True)
class RollResult:
    expression: str
    rolls: tuple[int, ...]
    modifier: int
    total: int


class DeterministicRNG:
    """Counter-based deterministic RNG with independent named streams.

    The implementation deliberately avoids process-global randomness. Its mutable counters
    live in ``WorldState`` so snapshots preserve future roll behavior exactly.
    """

    def __init__(self, seed: int, counters: dict[str, int]) -> None:
        self._seed = seed
        self._counters = counters

    def _die(self, sides: int, stream: str) -> int:
        if sides <= 0:
            raise ValueError("die sides must be positive")
        counter = self._counters.get(stream, 0) + 1
        self._counters[stream] = counter
        payload = f"rpg-engine:v1:{self._seed}:{stream}:{counter}".encode()
        digest = hashlib.blake2b(payload, digest_size=16).digest()
        return int.from_bytes(digest, "big") % sides + 1

    def roll(self, expression: str, *, stream: str = "default") -> RollResult:
        normalized = expression.replace(" ", "").lower()
        match = _DICE_RE.fullmatch(normalized)
        if not match:
            raise ValueError(f"unsupported dice expression: {expression!r}")
        count = int(match.group("count") or "1")
        sides = int(match.group("sides"))
        modifier = int(match.group("modifier") or "0")
        if not 1 <= count <= 1000:
            raise ValueError("dice count must be between 1 and 1000")
        rolls = tuple(self._die(sides, stream) for _ in range(count))
        return RollResult(
            expression=normalized,
            rolls=rolls,
            modifier=modifier,
            total=sum(rolls) + modifier,
        )
