"""Tests for deterministic random streams."""

from rpg_engine.dice import DeterministicRNG


def test_same_seed_and_stream_replay_identically() -> None:
    counters_a: dict[str, int] = {}
    counters_b: dict[str, int] = {}
    rng_a = DeterministicRNG(42, counters_a)
    rng_b = DeterministicRNG(42, counters_b)

    sequence_a = [rng_a.roll("1d20", stream="combat").total for _ in range(10)]
    sequence_b = [rng_b.roll("1d20", stream="combat").total for _ in range(10)]

    assert sequence_a == sequence_b
    assert counters_a == counters_b == {"combat": 10}


def test_named_streams_are_independent() -> None:
    counters: dict[str, int] = {}
    rng = DeterministicRNG(123, counters)
    rng.roll("1d20", stream="combat")
    rng.roll("2d6+3", stream="weather")

    assert counters == {"combat": 1, "weather": 2}
