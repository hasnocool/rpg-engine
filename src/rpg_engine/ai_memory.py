"""Deterministic persistent NPC memory retrieval helpers."""

from __future__ import annotations

from rpg_engine.models import NpcMemory, WorldState


class NpcMemoryContextStore:
    """Read facade over event-sourced NPC memories stored in WorldState."""

    def __init__(self, world: WorldState) -> None:
        self.world = world

    def relevant(
        self,
        actor_id: str,
        *,
        tags: set[str] | None = None,
        subject_ids: set[str] | None = None,
        limit: int = 12,
    ) -> list[NpcMemory]:
        if limit < 0:
            raise ValueError("limit cannot be negative")
        now = (
            self.world.calendar.absolute_minute
            if self.world.living_world_initialized
            else self.world.time_minutes
        )
        query_tags = tags or set()
        query_subjects = subject_ids or set()
        candidates = [
            memory
            for memory in self.world.npc_memories.get(actor_id, {}).values()
            if memory.expires_at_minute is None or memory.expires_at_minute > now
        ]
        candidates.sort(
            key=lambda memory: (
                -len(memory.tags & query_tags),
                -len(memory.subject_ids & query_subjects),
                -memory.importance,
                -memory.created_sequence,
                memory.id,
            )
        )
        return [memory.model_copy(deep=True) for memory in candidates[:limit]]
