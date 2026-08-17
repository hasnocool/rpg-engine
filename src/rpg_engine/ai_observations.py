"""Actor-centric observation filtering for AI decision providers."""

from __future__ import annotations

from pydantic import Field

from rpg_engine.ai_memory import NpcMemoryContextStore
from rpg_engine.content.models import ContentRegistry
from rpg_engine.models import ActionBudget, NpcMemory, Position, StrictModel, WorldState


class AiHealthObservation(StrictModel):
    current: int
    maximum: int


class AiActorObservation(StrictModel):
    id: str
    name: str
    tags: set[str] = Field(default_factory=set)
    position: Position
    health: AiHealthObservation | None = None
    conditions: set[str] = Field(default_factory=set)
    faction_id: str | None = None
    is_self: bool = False
    equipment: dict[str, str] = Field(default_factory=dict)
    resources: dict[str, int] = Field(default_factory=dict)


class AiExitObservation(StrictModel):
    connection_id: str
    destination_id: str
    destination_name: str
    travel_minutes: int


class AiLocationObservation(StrictModel):
    id: str
    name: str
    description: str = ""
    region: str | None = None
    exits: list[AiExitObservation] = Field(default_factory=list)
    discovered_container_ids: list[str] = Field(default_factory=list)


class AiEncounterObservation(StrictModel):
    id: str
    round: int
    active_actor_id: str | None = None
    participant_ids: list[str] = Field(default_factory=list)
    viewer_budget: ActionBudget | None = None


class AiQuestObservation(StrictModel):
    quest_id: str
    name: str
    state: str
    completed: bool


class AiDynamicQuestObservation(StrictModel):
    quest_id: str
    title: str
    description: str
    origin_location_id: str
    target_location_id: str
    status: str


class AiWeatherObservation(StrictModel):
    region_id: str
    condition: str
    temperature_c: int
    precipitation: float
    wind_kph: int


class AiSettlementObservation(StrictModel):
    settlement_id: str
    name: str
    prosperity: float
    price_index: dict[str, float] = Field(default_factory=dict)


class AiRumorObservation(StrictModel):
    rumor_id: str
    text: str
    dynamic_quest_id: str | None = None


class AiObservation(StrictModel):
    """Filtered state visible to one actor; never exposes the entire WorldState."""

    schema_version: int = 1
    campaign_id: str
    sequence: int
    time_minutes: int
    actor_id: str
    self_actor: AiActorObservation
    location: AiLocationObservation | None = None
    nearby_actors: list[AiActorObservation] = Field(default_factory=list)
    encounter: AiEncounterObservation | None = None
    quests: list[AiQuestObservation] = Field(default_factory=list)
    dynamic_quests: list[AiDynamicQuestObservation] = Field(default_factory=list)
    weather: AiWeatherObservation | None = None
    settlement: AiSettlementObservation | None = None
    rumors: list[AiRumorObservation] = Field(default_factory=list)
    faction_reputation: dict[str, int] = Field(default_factory=dict)
    memories: list[NpcMemory] = Field(default_factory=list)


def _health(world: WorldState, entity_id: str) -> AiHealthObservation | None:
    health = world.entities[entity_id].health
    if health is None:
        return None
    return AiHealthObservation(current=health.current, maximum=health.maximum)


def _actor(world: WorldState, entity_id: str, *, viewer_id: str) -> AiActorObservation:
    entity = world.entities[entity_id]
    is_self = entity_id == viewer_id
    return AiActorObservation(
        id=entity.id,
        name=entity.identity.name,
        tags=set(entity.identity.tags),
        position=entity.position.model_copy(deep=True),
        health=_health(world, entity.id),
        conditions=set(entity.conditions),
        faction_id=entity.faction_id,
        is_self=is_self,
        equipment=dict(entity.inventory.equipment) if is_self else {},
        resources=(
            {resource_id: pool.current for resource_id, pool in entity.resources.items()}
            if is_self
            else {}
        ),
    )


def build_ai_observation(
    world: WorldState,
    content: ContentRegistry,
    *,
    actor_id: str,
    memory_limit: int = 12,
    memory_tags: set[str] | None = None,
) -> AiObservation:
    """Build a deterministic, actor-scoped observation without mutating authoritative state."""

    if memory_limit < 0:
        raise ValueError("memory_limit cannot be negative")
    try:
        viewer = world.entities[actor_id]
    except KeyError as exc:
        raise KeyError(f"unknown actor: {actor_id}") from exc

    area_id = viewer.position.area
    region_id = viewer.position.region
    knowledge = world.knowledge.get(actor_id)

    location: AiLocationObservation | None = None
    if area_id is not None and area_id in content.locations:
        location_spec = content.locations[area_id]
        exits: list[AiExitObservation] = []
        for connection in sorted(content.connections.values(), key=lambda item: item.id):
            if area_id == connection.from_location_id:
                destination_id = connection.to_location_id
            elif connection.bidirectional and area_id == connection.to_location_id:
                destination_id = connection.from_location_id
            else:
                continue
            if connection.hidden and (
                knowledge is None or connection.id not in knowledge.connection_ids
            ):
                continue
            destination = content.locations.get(destination_id)
            exits.append(
                AiExitObservation(
                    connection_id=connection.id,
                    destination_id=destination_id,
                    destination_name=destination.name if destination else destination_id,
                    travel_minutes=connection.travel_minutes,
                )
            )
        discovered_containers = []
        if knowledge is not None:
            discovered_containers = sorted(
                container_id
                for container_id in knowledge.container_ids
                if container_id in content.containers
                and content.containers[container_id].location_id == area_id
            )
        location = AiLocationObservation(
            id=location_spec.id,
            name=location_spec.name,
            description=location_spec.description,
            region=location_spec.region,
            exits=exits,
            discovered_container_ids=discovered_containers,
        )

    visible_ids = sorted(
        entity.id
        for entity in world.entities.values()
        if entity.id != actor_id and area_id is not None and entity.position.area == area_id
    )

    encounter_obs: AiEncounterObservation | None = None
    for encounter in sorted(world.encounters.values(), key=lambda item: item.id):
        if encounter.active and actor_id in encounter.participant_ids:
            encounter_obs = AiEncounterObservation(
                id=encounter.id,
                round=encounter.round,
                active_actor_id=encounter.active_actor_id,
                participant_ids=list(encounter.participant_ids),
                viewer_budget=(
                    encounter.budgets[actor_id].model_copy(deep=True)
                    if actor_id in encounter.budgets
                    else None
                ),
            )
            break

    quests: list[AiQuestObservation] = []
    for progress in sorted(
        world.quest_progress.get(actor_id, {}).values(), key=lambda item: item.quest_id
    ):
        spec = content.quests.get(progress.quest_id)
        quests.append(
            AiQuestObservation(
                quest_id=progress.quest_id,
                name=spec.name if spec else progress.quest_id,
                state=progress.state,
                completed=progress.completed,
            )
        )

    known_locations = set(knowledge.location_ids) if knowledge is not None else set()
    if area_id is not None:
        known_locations.add(area_id)
    dynamic_quests = [
        AiDynamicQuestObservation(
            quest_id=quest.id,
            title=quest.title,
            description=quest.description,
            origin_location_id=quest.origin_location_id,
            target_location_id=quest.target_location_id,
            status=quest.status,
        )
        for quest in sorted(world.dynamic_quests.values(), key=lambda item: item.id)
        if quest.status == "active"
        and (
            quest.origin_location_id in known_locations
            or quest.target_location_id in known_locations
        )
    ]

    weather = None
    if region_id is not None and region_id in world.weather:
        state = world.weather[region_id]
        weather = AiWeatherObservation(
            region_id=state.region_id,
            condition=state.condition,
            temperature_c=state.temperature_c,
            precipitation=state.precipitation,
            wind_kph=state.wind_kph,
        )

    settlement = None
    if area_id is not None:
        matches = sorted(
            (
                state
                for state in world.settlements.values()
                if state.location_id == area_id
            ),
            key=lambda item: item.id,
        )
        if matches:
            state = matches[0]
            settlement = AiSettlementObservation(
                settlement_id=state.id,
                name=state.name,
                prosperity=state.prosperity,
                price_index=dict(state.price_index),
            )

    now = world.calendar.absolute_minute if world.living_world_initialized else world.time_minutes
    rumors = [
        AiRumorObservation(
            rumor_id=rumor.id,
            text=rumor.text,
            dynamic_quest_id=rumor.dynamic_quest_id,
        )
        for rumor in sorted(world.rumors.values(), key=lambda item: item.id)
        if rumor.location_id == area_id
        and (rumor.expires_at_minute is None or rumor.expires_at_minute > now)
    ]

    return AiObservation(
        campaign_id=world.campaign_id,
        sequence=world.sequence,
        time_minutes=world.time_minutes,
        actor_id=actor_id,
        self_actor=_actor(world, actor_id, viewer_id=actor_id),
        location=location,
        nearby_actors=[_actor(world, entity_id, viewer_id=actor_id) for entity_id in visible_ids],
        encounter=encounter_obs,
        quests=quests,
        dynamic_quests=dynamic_quests,
        weather=weather,
        settlement=settlement,
        rumors=rumors,
        faction_reputation=dict(world.reputation.get(actor_id, {})),
        memories=NpcMemoryContextStore(world).relevant(
            actor_id, tags=memory_tags, limit=memory_limit
        ),
    )
