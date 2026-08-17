"""Async campaign service providing concurrency-safe authoritative execution."""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator

from rpg_engine.character_creation import CharacterCreationCatalog, build_character_creation_catalog
from rpg_engine.commands import Command
from rpg_engine.content.models import ContentRegistry
from rpg_engine.events import Event
from rpg_engine.models import WorldState
from rpg_engine.observations import CampaignObservation, build_observation
from rpg_engine.persistence.sqlite import SQLiteEventStore
from rpg_engine.reducer import apply_event
from rpg_engine.rules.base import RulesRuntime
from rpg_engine.rules.d20 import D20RulesRuntime
from rpg_engine.temporal import TimelineSimulationEngine


class CampaignService:
    """Owns per-campaign locks so concurrent clients cannot interleave mutations."""

    def __init__(
        self,
        store: SQLiteEventStore,
        *,
        content: ContentRegistry | None = None,
        rules: RulesRuntime | None = None,
        snapshot_interval: int = 100,
    ) -> None:
        self.store = store
        self.content = content or ContentRegistry.with_core_defaults()
        self.rules = rules or D20RulesRuntime()
        self.snapshot_interval = max(1, snapshot_interval)
        self._engines: dict[str, TimelineSimulationEngine] = {}
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._event_conditions: defaultdict[str, asyncio.Condition] = defaultdict(asyncio.Condition)
        self._event_generations: defaultdict[str, int] = defaultdict(int)

    async def create_campaign(self, seed: int, *, campaign_id: str | None = None) -> WorldState:
        campaign_id = campaign_id or str(uuid.uuid4())
        world = WorldState(campaign_id=campaign_id, seed=seed)
        await self.store.create_campaign(campaign_id, seed)
        await self.store.save_snapshot(world)
        self._engines[campaign_id] = TimelineSimulationEngine(
            world, rules=self.rules, content=self.content
        )
        return world.model_copy(deep=True)

    async def _load_engine(self, campaign_id: str) -> TimelineSimulationEngine:
        cached = self._engines.get(campaign_id)
        if cached is not None:
            return cached

        snapshot = await self.store.load_latest_snapshot(campaign_id)
        if snapshot is None:
            seed = await self.store.get_seed(campaign_id)
            snapshot = WorldState(campaign_id=campaign_id, seed=seed)
        events = await self.store.list_events(campaign_id, after_sequence=snapshot.sequence)
        for event in events:
            apply_event(snapshot, event)
        engine = TimelineSimulationEngine(snapshot, rules=self.rules, content=self.content)
        self._engines[campaign_id] = engine
        return engine

    async def _notify_event_subscribers(self, campaign_id: str) -> None:
        condition = self._event_conditions[campaign_id]
        async with condition:
            self._event_generations[campaign_id] += 1
            condition.notify_all()

    async def execute(self, campaign_id: str, command: Command) -> list[Event]:
        async with self._locks[campaign_id]:
            engine = await self._load_engine(campaign_id)
            events: list[Event] = engine.execute(command)
            await self.store.append_events(campaign_id, events)
            if engine.world.sequence % self.snapshot_interval < len(events):
                await self.store.save_snapshot(engine.world)
        if events:
            await self._notify_event_subscribers(campaign_id)
        return events

    async def state(self, campaign_id: str) -> WorldState:
        async with self._locks[campaign_id]:
            engine = await self._load_engine(campaign_id)
            return engine.world.model_copy(deep=True)

    async def observation(
        self, campaign_id: str, *, actor_id: str | None = None
    ) -> CampaignObservation:
        async with self._locks[campaign_id]:
            engine = await self._load_engine(campaign_id)
            return build_observation(engine.world, self.content, viewer_id=actor_id)

    async def character_creation_catalog(self) -> CharacterCreationCatalog:
        return build_character_creation_catalog(self.content)

    async def events(self, campaign_id: str, *, after_sequence: int = 0) -> list[Event]:
        await self.store.get_seed(campaign_id)
        return await self.store.list_events(campaign_id, after_sequence=after_sequence)

    async def stream_events(
        self,
        campaign_id: str,
        *,
        after_sequence: int = 0,
        heartbeat_seconds: float = 20.0,
    ) -> AsyncIterator[list[Event]]:
        """Yield ordered event batches and empty heartbeat batches without losing resume cursors."""

        await self.store.get_seed(campaign_id)
        cursor = after_sequence
        condition = self._event_conditions[campaign_id]

        while True:
            events = await self.store.list_events(campaign_id, after_sequence=cursor)
            if events:
                cursor = events[-1].sequence
                yield events
                continue

            heartbeat = False
            async with condition:
                generation = self._event_generations[campaign_id]
                events = await self.store.list_events(campaign_id, after_sequence=cursor)
                if events:
                    continue
                try:
                    await asyncio.wait_for(
                        condition.wait_for(
                            lambda generation=generation: (
                                self._event_generations[campaign_id] != generation
                            )
                        ),
                        timeout=heartbeat_seconds,
                    )
                except TimeoutError:
                    heartbeat = True
            if heartbeat:
                yield []
