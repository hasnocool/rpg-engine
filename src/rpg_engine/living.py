"""Authoritative v0.4 living-world systems."""

from __future__ import annotations

from collections.abc import Iterable

from rpg_engine.commands import (
    AdjustFactionRelationCommand,
    AdjustReputationCommand,
    Command,
    CompleteDynamicQuestCommand,
    GenerateDynamicQuestCommand,
    GenerateRumorCommand,
    HarvestResourceCommand,
    InitializeLivingWorldCommand,
    ResolveOffscreenEncounterCommand,
)
from rpg_engine.content.models import (
    CalendarSpec,
    ContentRegistry,
    DynamicQuestTemplateSpec,
    NpcScheduleSpec,
    RumorTemplateSpec,
    WeatherOptionSpec,
    WeatherProfileSpec,
)
from rpg_engine.dice import DeterministicRNG
from rpg_engine.events import (
    CalendarAdvancedEvent,
    DynamicQuestGeneratedEvent,
    DynamicQuestUpdatedEvent,
    EventBase,
    FactionRelationChangedEvent,
    LivingWorldInitializedEvent,
    NpcScheduleAppliedEvent,
    OffscreenEncounterResolvedEvent,
    ReputationChangedEvent,
    ResourceHarvestedEvent,
    ResourceNodeInitializedEvent,
    ResourceRegeneratedEvent,
    RumorGeneratedEvent,
    SettlementEconomyTickedEvent,
    SettlementInitializedEvent,
    TimelineItemScheduledEvent,
    WeatherChangedEvent,
)
from rpg_engine.living_hooks import EcologyHookRegistry
from rpg_engine.models import (
    CalendarState,
    DynamicQuestState,
    Entity,
    NpcScheduleState,
    OffscreenEncounterRecord,
    Position,
    ResourceNodeState,
    RumorState,
    SettlementState,
    WeatherState,
    WorldState,
)
from rpg_engine.timeline import TimelineItem, TimelineItemKind, TimelineScheduler


class LivingWorldError(ValueError):
    """Rejected living-world command or scheduled world job."""


class LivingWorldRuntime:
    """Calendar, weather, schedules, factions, economy, rumors, and ecology authority."""

    def __init__(
        self,
        world: WorldState,
        *,
        content: ContentRegistry,
        rng: DeterministicRNG,
        timeline: TimelineScheduler,
        ecology_hooks: EcologyHookRegistry | None = None,
    ) -> None:
        self.world = world
        self.content = content
        self.rng = rng
        self.timeline = timeline
        self.ecology_hooks = ecology_hooks or EcologyHookRegistry()

    @staticmethod
    def handles(command: Command) -> bool:
        return isinstance(
            command,
            (
                InitializeLivingWorldCommand,
                AdjustFactionRelationCommand,
                AdjustReputationCommand,
                ResolveOffscreenEncounterCommand,
                GenerateRumorCommand,
                GenerateDynamicQuestCommand,
                CompleteDynamicQuestCommand,
                HarvestResourceCommand,
            ),
        )

    def _entity(self, entity_id: str) -> Entity:
        try:
            return self.world.entities[entity_id]
        except KeyError as exc:
            raise LivingWorldError(f"unknown entity: {entity_id}") from exc

    def _calendar_spec(self) -> CalendarSpec:
        if self.content.calendars:
            calendar_id = sorted(self.content.calendars)[0]
            return self.content.calendars[calendar_id]
        return CalendarSpec(id="default")

    @staticmethod
    def _clamp_relation(value: int) -> int:
        return max(-100, min(100, value))

    def _calendar_for_minute(self, absolute_minute: int) -> CalendarState:
        spec = self._calendar_spec()
        day_index, minute_of_day = divmod(absolute_minute, spec.minutes_per_day)
        year_offset, year_day_index = divmod(day_index, spec.days_per_year)
        day_of_year = year_day_index + 1
        season = spec.seasons[0].name
        for candidate in spec.seasons:
            if candidate.start_day <= day_of_year:
                season = candidate.name
            else:
                break
        return CalendarState(
            calendar_id=spec.id,
            absolute_minute=absolute_minute,
            year=spec.starting_year + year_offset,
            day_of_year=day_of_year,
            day=day_index + 1,
            minute_of_day=minute_of_day,
            season=season,
        )

    def calendar_events(self, now_ms: int) -> list[EventBase]:
        state = self._calendar_for_minute(now_ms // 60_000)
        if state == self.world.calendar:
            return []
        self.world.calendar = state
        return [CalendarAdvancedEvent(calendar=state.model_copy(deep=True))]

    def expire_dynamic_quests(self, now_minute: int) -> list[EventBase]:
        events: list[EventBase] = []
        for quest_id in sorted(self.world.dynamic_quests):
            quest = self.world.dynamic_quests[quest_id]
            if (
                quest.status == "active"
                and quest.expires_at_minute is not None
                and quest.expires_at_minute <= now_minute
            ):
                quest.status = "expired"
                events.append(DynamicQuestUpdatedEvent(quest=quest.model_copy(deep=True)))
        return events

    def _schedule_job(
        self,
        item_id: str,
        *,
        job_type: str,
        target_id: str,
        interval_minutes: int,
        kind: TimelineItemKind = TimelineItemKind.WORLD_EVENT,
    ) -> TimelineItemScheduledEvent:
        interval_ms = interval_minutes * 60_000
        item = self.timeline.schedule(
            item_id,
            kind,
            delay_ms=interval_ms,
            interval_ms=interval_ms,
            payload={"job_type": job_type, "target_id": target_id},
        )
        return TimelineItemScheduledEvent(item=item)

    def _weather_option(self, profile: WeatherProfileSpec) -> WeatherOptionSpec:
        total_weight = sum(option.weight for option in profile.options)
        roll = self.rng.roll(
            f"1d{total_weight}",
            stream=f"living:weather:{profile.id}:{self.world.calendar.absolute_minute}",
        ).total
        cursor = 0
        for option in profile.options:
            cursor += option.weight
            if roll <= cursor:
                return option
        return profile.options[-1]

    def _range_roll(self, minimum: int, maximum: int, stream: str) -> int:
        if minimum == maximum:
            return minimum
        span = maximum - minimum + 1
        return minimum + self.rng.roll(f"1d{span}", stream=stream).total - 1

    def _tick_weather(self, profile_id: str) -> list[EventBase]:
        try:
            profile = self.content.weather_profiles[profile_id]
        except KeyError as exc:
            raise LivingWorldError(f"unknown weather profile: {profile_id}") from exc
        option = self._weather_option(profile)
        now = self.world.calendar.absolute_minute
        temperature = self._range_roll(
            option.temperature_min_c,
            option.temperature_max_c,
            f"living:weather:temperature:{profile.id}:{now}",
        )
        wind = self._range_roll(
            option.wind_min_kph,
            option.wind_max_kph,
            f"living:weather:wind:{profile.id}:{now}",
        )
        state = WeatherState(
            profile_id=profile.id,
            region_id=profile.region_id,
            condition=option.condition,
            temperature_c=temperature,
            precipitation=option.precipitation,
            wind_kph=wind,
            updated_at_minute=now,
        )
        self.world.weather[profile.id] = state
        return [WeatherChangedEvent(weather=state.model_copy(deep=True))]

    def _initialize_factions(self) -> list[EventBase]:
        events: list[EventBase] = []
        seen: set[tuple[str, str]] = set()
        for faction_id in sorted(self.content.factions):
            self.world.faction_relations.setdefault(faction_id, {})
        for faction_id, spec in sorted(self.content.factions.items()):
            for other_id, value in sorted(spec.base_relations.items()):
                pair = tuple(sorted((faction_id, other_id)))
                if pair in seen:
                    continue
                seen.add(pair)
                previous = self.world.faction_relations[faction_id].get(other_id, 0)
                current = self._clamp_relation(value)
                self.world.faction_relations[faction_id][other_id] = current
                self.world.faction_relations.setdefault(other_id, {})[faction_id] = current
                events.append(
                    FactionRelationChangedEvent(
                        faction_a_id=faction_id,
                        faction_b_id=other_id,
                        previous=previous,
                        current=current,
                        reason="initial_content",
                    )
                )
        return events

    def _initialize_settlements(self) -> list[EventBase]:
        events: list[EventBase] = []
        for settlement_id, spec in sorted(self.content.settlements.items()):
            state = SettlementState(
                id=spec.id,
                name=spec.name,
                location_id=spec.location_id,
                faction_id=spec.faction_id,
                population=spec.population,
                treasury=spec.treasury,
                prosperity=spec.prosperity,
                stocks=dict(spec.initial_stocks),
                price_index={resource: 1.0 for resource in spec.initial_stocks},
                updated_at_minute=self.world.calendar.absolute_minute,
            )
            self.world.settlements[settlement_id] = state
            events.append(SettlementInitializedEvent(settlement=state.model_copy(deep=True)))
            events.append(
                self._schedule_job(
                    f"living:economy:{settlement_id}",
                    job_type="settlement_economy",
                    target_id=settlement_id,
                    interval_minutes=spec.tick_interval_minutes,
                )
            )
        return events

    def _initialize_resources(self) -> list[EventBase]:
        events: list[EventBase] = []
        for node_id, spec in sorted(self.content.resource_nodes.items()):
            state = ResourceNodeState(
                id=spec.id,
                location_id=spec.location_id,
                item_id=spec.item_id,
                amount=spec.initial_amount,
                capacity=spec.capacity,
                last_regen_minute=self.world.calendar.absolute_minute,
            )
            self.world.resource_nodes[node_id] = state
            events.append(ResourceNodeInitializedEvent(node=state.model_copy(deep=True)))
            events.append(
                self._schedule_job(
                    f"living:ecology:{node_id}",
                    job_type="resource_regen",
                    target_id=node_id,
                    interval_minutes=spec.regen_interval_minutes,
                )
            )
        return events

    def _initialize_weather(self) -> list[EventBase]:
        events: list[EventBase] = []
        for profile_id, spec in sorted(self.content.weather_profiles.items()):
            events.extend(self._tick_weather(profile_id))
            events.append(
                self._schedule_job(
                    f"living:weather:{profile_id}",
                    job_type="weather",
                    target_id=profile_id,
                    interval_minutes=spec.update_interval_minutes,
                )
            )
        return events

    def _initialize_npc_schedules(self) -> list[EventBase]:
        events: list[EventBase] = []
        for schedule_id, schedule in sorted(self.content.npc_schedules.items()):
            events.append(
                self._schedule_job(
                    f"living:npc-schedule:{schedule_id}",
                    job_type="npc_schedule",
                    target_id=schedule_id,
                    interval_minutes=schedule.tick_interval_minutes,
                    kind=TimelineItemKind.NPC_SCHEDULE,
                )
            )
        return events

    def _initialize_rumors(self) -> list[EventBase]:
        events: list[EventBase] = []
        for rumor_id, rumor in sorted(self.content.rumor_templates.items()):
            events.append(
                self._schedule_job(
                    f"living:rumor:{rumor_id}",
                    job_type="rumor",
                    target_id=rumor_id,
                    interval_minutes=rumor.interval_minutes,
                )
            )
        return events

    def _initialize(self) -> list[EventBase]:
        if self.world.living_world_initialized:
            raise LivingWorldError("living world is already initialized")
        self.world.calendar = self._calendar_for_minute(self.timeline.state.now_ms // 60_000)
        events: list[EventBase] = [
            LivingWorldInitializedEvent(initialized_at_ms=self.timeline.state.now_ms),
            CalendarAdvancedEvent(calendar=self.world.calendar.model_copy(deep=True)),
        ]
        self.world.living_world_initialized = True
        events.extend(self._initialize_factions())
        events.extend(self._initialize_settlements())
        events.extend(self._initialize_resources())
        events.extend(self._initialize_weather())
        events.extend(self._initialize_npc_schedules())
        events.extend(self._initialize_rumors())
        return events

    def _adjust_faction_relation(self, command: AdjustFactionRelationCommand) -> list[EventBase]:
        if command.faction_a_id == command.faction_b_id:
            raise LivingWorldError("cannot adjust a faction's relation with itself")
        if command.faction_a_id not in self.content.factions:
            raise LivingWorldError(f"unknown faction: {command.faction_a_id}")
        if command.faction_b_id not in self.content.factions:
            raise LivingWorldError(f"unknown faction: {command.faction_b_id}")
        relations = self.world.faction_relations.setdefault(command.faction_a_id, {})
        previous = relations.get(command.faction_b_id, 0)
        current = self._clamp_relation(previous + command.delta)
        relations[command.faction_b_id] = current
        self.world.faction_relations.setdefault(command.faction_b_id, {})[
            command.faction_a_id
        ] = current
        return [
            FactionRelationChangedEvent(
                faction_a_id=command.faction_a_id,
                faction_b_id=command.faction_b_id,
                previous=previous,
                current=current,
                reason=command.reason,
            )
        ]

    def _adjust_reputation(self, command: AdjustReputationCommand) -> list[EventBase]:
        self._entity(command.actor_id)
        if command.faction_id not in self.content.factions:
            raise LivingWorldError(f"unknown faction: {command.faction_id}")
        reputations = self.world.reputation.setdefault(command.actor_id, {})
        previous = reputations.get(command.faction_id, 0)
        current = self._clamp_relation(previous + command.delta)
        reputations[command.faction_id] = current
        return [
            ReputationChangedEvent(
                actor_id=command.actor_id,
                faction_id=command.faction_id,
                previous=previous,
                current=current,
                reason=command.reason,
            )
        ]

    @staticmethod
    def _unit_power(entity: Entity) -> int:
        health = entity.health.current if entity.health is not None else 10
        return max(
            1,
            health
            + entity.stats.armor_class
            + entity.stats.strength
            + entity.stats.dexterity,
        )

    def _require_offscreen(self, entity_ids: Iterable[str]) -> list[Entity]:
        entities = [self._entity(entity_id) for entity_id in entity_ids]
        for entity in entities:
            if not entity.is_alive:
                raise LivingWorldError("defeated entities cannot join off-screen encounters")
            if any(
                encounter.active and entity.id in encounter.participant_ids
                for encounter in self.world.encounters.values()
            ):
                raise LivingWorldError("active tactical participants cannot resolve off-screen")
        return entities

    def _resolve_offscreen(self, command: ResolveOffscreenEncounterCommand) -> list[EventBase]:
        if command.encounter_id in self.world.offscreen_encounters:
            raise LivingWorldError(f"off-screen encounter already resolved: {command.encounter_id}")
        if len(set(command.attacker_ids)) != len(command.attacker_ids):
            raise LivingWorldError("off-screen attacker IDs must be unique")
        if len(set(command.defender_ids)) != len(command.defender_ids):
            raise LivingWorldError("off-screen defender IDs must be unique")
        if set(command.attacker_ids) & set(command.defender_ids):
            raise LivingWorldError("off-screen encounter sides must be disjoint")
        if command.location_id is not None and command.location_id not in self.content.locations:
            raise LivingWorldError(f"unknown encounter location: {command.location_id}")
        attackers = self._require_offscreen(command.attacker_ids)
        defenders = self._require_offscreen(command.defender_ids)
        if command.location_id is not None and any(
            entity.position.area != command.location_id for entity in [*attackers, *defenders]
        ):
            raise LivingWorldError("off-screen encounter participants must be at the location")
        attacker_score = sum(self._unit_power(entity) for entity in attackers)
        defender_score = sum(self._unit_power(entity) for entity in defenders)
        attacker_score += self.rng.roll(
            "1d20", stream=f"living:offscreen:{command.encounter_id}:attackers"
        ).total
        defender_score += self.rng.roll(
            "1d20", stream=f"living:offscreen:{command.encounter_id}:defenders"
        ).total
        attackers_win = attacker_score >= defender_score
        winners = attackers if attackers_win else defenders
        losers = defenders if attackers_win else attackers
        margin = abs(attacker_score - defender_score)
        loser_damage = max(1, margin // max(1, len(losers) * 3) + 1)
        winner_damage = max(0, loser_damage // 3)
        health_after: dict[str, int] = {}
        defeated_ids: list[str] = []
        for entity in [*winners, *losers]:
            if entity.health is None:
                continue
            damage = winner_damage if entity in winners else loser_damage
            entity.health.current = max(0, entity.health.current - damage)
            health_after[entity.id] = entity.health.current
            if entity.health.current == 0:
                defeated_ids.append(entity.id)
        record = OffscreenEncounterRecord(
            id=command.encounter_id,
            location_id=command.location_id,
            attacker_ids=list(command.attacker_ids),
            defender_ids=list(command.defender_ids),
            attacker_score=attacker_score,
            defender_score=defender_score,
            winner="attackers" if attackers_win else "defenders",
            health_after=health_after,
            defeated_ids=sorted(defeated_ids),
            resolved_at_minute=self.world.calendar.absolute_minute,
        )
        self.world.offscreen_encounters[record.id] = record
        return [OffscreenEncounterResolvedEvent(record=record.model_copy(deep=True))]

    def _eligible_dynamic_templates(
        self, origin_location_id: str
    ) -> list[DynamicQuestTemplateSpec]:
        return [
            template
            for template in self.content.dynamic_quest_templates.values()
            if origin_location_id in self.content.locations
            and template.target_location_ids
        ]

    def _pick_dynamic_template(
        self, origin_location_id: str, template_id: str | None
    ) -> DynamicQuestTemplateSpec:
        if template_id is not None:
            try:
                return self.content.dynamic_quest_templates[template_id]
            except KeyError as exc:
                raise LivingWorldError(f"unknown dynamic quest template: {template_id}") from exc
        candidates = sorted(
            self._eligible_dynamic_templates(origin_location_id), key=lambda item: item.id
        )
        if not candidates:
            raise LivingWorldError("no dynamic quest templates are available")
        roll = self.rng.roll(
            f"1d{len(candidates)}",
            stream=f"living:dynamic-quest-template:{origin_location_id}",
        ).total
        return candidates[roll - 1]

    def _generate_dynamic_quest(
        self, origin_location_id: str, template_id: str | None = None
    ) -> tuple[DynamicQuestState, list[EventBase]]:
        if origin_location_id not in self.content.locations:
            raise LivingWorldError(f"unknown origin location: {origin_location_id}")
        template = self._pick_dynamic_template(origin_location_id, template_id)
        target_roll = self.rng.roll(
            f"1d{len(template.target_location_ids)}",
            stream=f"living:dynamic-quest-target:{template.id}:{origin_location_id}",
        ).total
        target_id = template.target_location_ids[target_roll - 1]
        now = self.world.calendar.absolute_minute
        quest_id = (
            f"dynamic:{template.id}:{self.world.sequence + 1}:"
            f"{len(self.world.dynamic_quests)}"
        )
        expires_at = (
            None
            if template.expires_after_minutes is None
            else now + template.expires_after_minutes
        )
        quest = DynamicQuestState(
            id=quest_id,
            template_id=template.id,
            title=template.title,
            description=template.description,
            origin_location_id=origin_location_id,
            target_location_id=target_id,
            generated_at_minute=now,
            expires_at_minute=expires_at,
        )
        self.world.dynamic_quests[quest.id] = quest
        return quest, [DynamicQuestGeneratedEvent(quest=quest.model_copy(deep=True))]

    def _pick_rumor_template(
        self, location_id: str | None, template_id: str | None
    ) -> RumorTemplateSpec:
        if template_id is not None:
            try:
                return self.content.rumor_templates[template_id]
            except KeyError as exc:
                raise LivingWorldError(f"unknown rumor template: {template_id}") from exc
        candidates = [
            rumor
            for rumor in self.content.rumor_templates.values()
            if location_id is None or rumor.location_id == location_id
        ]
        candidates.sort(key=lambda item: item.id)
        if not candidates:
            raise LivingWorldError("no rumor templates are available")
        total_weight = sum(rumor.weight for rumor in candidates)
        roll = self.rng.roll(
            f"1d{total_weight}",
            stream=f"living:rumor-template:{location_id or 'any'}",
        ).total
        cursor = 0
        for rumor in candidates:
            cursor += rumor.weight
            if roll <= cursor:
                return rumor
        return candidates[-1]

    def _generate_rumor(
        self, location_id: str | None = None, template_id: str | None = None
    ) -> list[EventBase]:
        template = self._pick_rumor_template(location_id, template_id)
        now = self.world.calendar.absolute_minute
        rumor_id = f"rumor:{template.id}:{self.world.sequence + 1}:{len(self.world.rumors)}"
        dynamic_quest_id: str | None = None
        quest_events: list[EventBase] = []
        if template.quest_template_id is not None:
            quest, quest_events = self._generate_dynamic_quest(
                template.location_id, template.quest_template_id
            )
            dynamic_quest_id = quest.id
        rumor = RumorState(
            id=rumor_id,
            template_id=template.id,
            text=template.text,
            location_id=template.location_id,
            generated_at_minute=now,
            expires_at_minute=(
                None
                if template.expires_after_minutes is None
                else now + template.expires_after_minutes
            ),
            dynamic_quest_id=dynamic_quest_id,
        )
        self.world.rumors[rumor.id] = rumor
        return [RumorGeneratedEvent(rumor=rumor.model_copy(deep=True)), *quest_events]

    def _complete_dynamic_quest(self, command: CompleteDynamicQuestCommand) -> list[EventBase]:
        actor = self._entity(command.actor_id)
        try:
            quest = self.world.dynamic_quests[command.quest_id]
        except KeyError as exc:
            raise LivingWorldError(f"unknown dynamic quest: {command.quest_id}") from exc
        if quest.status != "active":
            raise LivingWorldError("dynamic quest is not active")
        if actor.position.area != quest.target_location_id:
            raise LivingWorldError("actor is not at the dynamic quest target")
        template = self.content.dynamic_quest_templates[quest.template_id]
        quest.status = "completed"
        balance_after: int | None = None
        if template.reward_amount:
            balance_after = actor.inventory.currency.get(template.reward_currency, 0)
            balance_after += template.reward_amount
            actor.inventory.currency[template.reward_currency] = balance_after
        return [
            DynamicQuestUpdatedEvent(
                quest=quest.model_copy(deep=True),
                actor_id=actor.id,
                reward_currency=template.reward_currency,
                reward_amount=template.reward_amount,
                actor_balance_after=balance_after,
            )
        ]

    def _harvest(self, command: HarvestResourceCommand) -> list[EventBase]:
        actor = self._entity(command.actor_id)
        try:
            node = self.world.resource_nodes[command.node_id]
        except KeyError as exc:
            raise LivingWorldError(f"unknown resource node: {command.node_id}") from exc
        if actor.position.area != node.location_id:
            raise LivingWorldError("actor is not at the resource node")
        if node.amount < command.amount:
            raise LivingWorldError("resource node does not contain requested amount")
        node.amount -= command.amount
        actor.inventory.item_ids.extend([node.item_id] * command.amount)
        return [
            ResourceHarvestedEvent(
                actor_id=actor.id,
                node_id=node.id,
                item_id=node.item_id,
                amount=command.amount,
                node_amount_after=node.amount,
                actor_item_ids_after=list(actor.inventory.item_ids),
            )
        ]

    def _settlement_tick(self, settlement_id: str) -> list[EventBase]:
        try:
            state = self.world.settlements[settlement_id]
            spec = self.content.settlements[settlement_id]
        except KeyError as exc:
            raise LivingWorldError(f"unknown settlement: {settlement_id}") from exc
        resources = sorted(
            set(state.stocks) | set(spec.production_per_tick) | set(spec.consumption_per_tick)
        )
        unmet = 0
        for resource in resources:
            available = state.stocks.get(resource, 0) + spec.production_per_tick.get(resource, 0)
            demand = spec.consumption_per_tick.get(resource, 0)
            consumed = min(available, demand)
            state.stocks[resource] = available - consumed
            unmet += demand - consumed
            state.price_index[resource] = round(
                1.0 + min(2.0, (demand - consumed) / max(1, demand)), 3
            )
        state.treasury = max(0, state.treasury + spec.income_per_tick - spec.expenses_per_tick)
        prosperity_delta = -0.02 if unmet else 0.01
        if state.treasury == 0 and spec.expenses_per_tick:
            prosperity_delta -= 0.01
        state.prosperity = round(max(0.0, min(2.0, state.prosperity + prosperity_delta)), 3)
        state.updated_at_minute = self.world.calendar.absolute_minute
        return [SettlementEconomyTickedEvent(settlement=state.model_copy(deep=True))]

    def _schedule_entry(self, schedule: NpcScheduleSpec) -> tuple[str, str]:
        minute = self.world.calendar.minute_of_day
        selected = schedule.entries[-1]
        for entry in schedule.entries:
            if entry.start_minute <= minute:
                selected = entry
            else:
                break
        return selected.location_id, selected.activity

    def _npc_schedule_tick(self, schedule_id: str) -> list[EventBase]:
        try:
            schedule = self.content.npc_schedules[schedule_id]
        except KeyError as exc:
            raise LivingWorldError(f"unknown NPC schedule: {schedule_id}") from exc
        location_id, activity = self._schedule_entry(schedule)
        location = self.content.locations[location_id]
        events: list[EventBase] = []
        for actor_id, template_id in sorted(self.world.entity_templates.items()):
            template = self.content.npc_templates.get(template_id)
            if template is None or template.schedule_id != schedule_id:
                continue
            actor = self.world.entities.get(actor_id)
            if actor is None or any(
                encounter.active and actor_id in encounter.participant_ids
                for encounter in self.world.encounters.values()
            ):
                continue
            previous = self.world.npc_schedules.get(actor_id)
            if (
                previous is not None
                and previous.location_id == location_id
                and previous.activity == activity
            ):
                continue
            actor.position = Position(
                world=actor.position.world,
                region=location.region,
                area=location.id,
            )
            state = NpcScheduleState(
                actor_id=actor_id,
                schedule_id=schedule_id,
                location_id=location_id,
                activity=activity,
                updated_at_minute=self.world.calendar.absolute_minute,
            )
            self.world.npc_schedules[actor_id] = state
            events.append(
                NpcScheduleAppliedEvent(
                    schedule=state.model_copy(deep=True),
                    position=actor.position.model_copy(deep=True),
                )
            )
        return events

    def _weather_for_location(self, location_id: str) -> WeatherState | None:
        location = self.content.locations.get(location_id)
        if location is None or location.region is None:
            return None
        candidates = [
            state for state in self.world.weather.values() if state.region_id == location.region
        ]
        return min(candidates, key=lambda state: state.profile_id) if candidates else None

    def _resource_regen(self, node_id: str) -> list[EventBase]:
        try:
            node = self.world.resource_nodes[node_id]
            spec = self.content.resource_nodes[node_id]
        except KeyError as exc:
            raise LivingWorldError(f"unknown resource node: {node_id}") from exc
        weather = self._weather_for_location(node.location_id)
        multiplier = self.ecology_hooks.regen_multiplier(node, weather, self.world)
        amount = max(0, int(round(spec.regen_amount * multiplier)))
        previous = node.amount
        node.amount = min(node.capacity, node.amount + amount)
        node.last_regen_minute = self.world.calendar.absolute_minute
        actual = node.amount - previous
        return [
            ResourceRegeneratedEvent(
                node_id=node.id,
                amount=actual,
                amount_after=node.amount,
                last_regen_minute=node.last_regen_minute,
                weather_condition=weather.condition if weather else None,
            )
        ]

    def on_timeline_item(self, item: TimelineItem) -> list[EventBase]:
        job_type = item.payload.get("job_type")
        target_id = item.payload.get("target_id")
        if not isinstance(job_type, str) or not isinstance(target_id, str):
            return []
        if job_type == "weather":
            return self._tick_weather(target_id)
        if job_type == "settlement_economy":
            return self._settlement_tick(target_id)
        if job_type == "npc_schedule":
            return self._npc_schedule_tick(target_id)
        if job_type == "resource_regen":
            return self._resource_regen(target_id)
        if job_type == "rumor":
            return self._generate_rumor(template_id=target_id)
        return []

    def execute(self, command: Command) -> list[EventBase]:
        if isinstance(command, InitializeLivingWorldCommand):
            return self._initialize()
        if isinstance(command, AdjustFactionRelationCommand):
            return self._adjust_faction_relation(command)
        if isinstance(command, AdjustReputationCommand):
            return self._adjust_reputation(command)
        if isinstance(command, ResolveOffscreenEncounterCommand):
            return self._resolve_offscreen(command)
        if isinstance(command, GenerateRumorCommand):
            return self._generate_rumor(command.location_id, command.template_id)
        if isinstance(command, GenerateDynamicQuestCommand):
            _, events = self._generate_dynamic_quest(
                command.origin_location_id, command.template_id
            )
            return events
        if isinstance(command, CompleteDynamicQuestCommand):
            return self._complete_dynamic_quest(command)
        if isinstance(command, HarvestResourceCommand):
            return self._harvest(command)
        raise LivingWorldError(f"unsupported living-world command: {type(command).__name__}")