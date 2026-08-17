"""Renderer-neutral campaign observation models for v0.5+ clients."""

from __future__ import annotations

from pydantic import Field

from rpg_engine.content.models import ContentRegistry
from rpg_engine.models import ActionBudget, Position, StrictModel, WorldState


class HealthObservation(StrictModel):
    current: int
    maximum: int


class ActorObservation(StrictModel):
    id: str
    name: str
    tags: set[str] = Field(default_factory=set)
    position: Position
    health: HealthObservation | None = None
    conditions: set[str] = Field(default_factory=set)
    faction_id: str | None = None
    equipment: dict[str, str] = Field(default_factory=dict)
    currency: dict[str, int] = Field(default_factory=dict)
    ancestry_id: str | None = None
    class_id: str | None = None
    background_id: str | None = None
    level: int | None = None
    pronouns: str = ""
    appearance: str = ""


class ExitObservation(StrictModel):
    connection_id: str
    destination_id: str
    destination_name: str
    travel_minutes: int
    hidden: bool = False


class LocationObservation(StrictModel):
    id: str
    name: str
    description: str = ""
    region: str | None = None
    exits: list[ExitObservation] = Field(default_factory=list)
    discovered_container_ids: list[str] = Field(default_factory=list)


class EncounterObservation(StrictModel):
    id: str
    round: int
    active_actor_id: str | None = None
    participant_ids: list[str] = Field(default_factory=list)
    viewer_budget: ActionBudget | None = None


class QuestObservation(StrictModel):
    quest_id: str
    name: str
    state: str
    completed: bool


class DialogueObservation(StrictModel):
    session_id: str
    npc_id: str
    dialogue_id: str
    node_id: str
    active: bool


class CampaignObservation(StrictModel):
    """Presentation-neutral state intended for CLI/TUI/browser/SSH consumers."""

    schema_version: int = 1
    campaign_id: str
    sequence: int
    time_minutes: int
    viewer_id: str | None = None
    location: LocationObservation | None = None
    actors: list[ActorObservation] = Field(default_factory=list)
    encounters: list[EncounterObservation] = Field(default_factory=list)
    quests: list[QuestObservation] = Field(default_factory=list)
    dialogues: list[DialogueObservation] = Field(default_factory=list)


def _actor_observation(world: WorldState, entity_id: str) -> ActorObservation:
    entity = world.entities[entity_id]
    health = None
    if entity.health is not None:
        health = HealthObservation(current=entity.health.current, maximum=entity.health.maximum)
    character = world.characters.get(entity_id)
    return ActorObservation(
        id=entity.id,
        name=entity.identity.name,
        tags=set(entity.identity.tags),
        position=entity.position.model_copy(deep=True),
        health=health,
        conditions=set(entity.conditions),
        faction_id=entity.faction_id,
        equipment=dict(entity.inventory.equipment),
        currency=dict(entity.inventory.currency),
        ancestry_id=character.ancestry_id if character is not None else None,
        class_id=character.class_id if character is not None else None,
        background_id=character.background_id if character is not None else None,
        level=character.level if character is not None else None,
        pronouns=character.description.pronouns if character is not None else "",
        appearance=character.description.appearance if character is not None else "",
    )


def build_observation(
    world: WorldState,
    content: ContentRegistry,
    *,
    viewer_id: str | None = None,
) -> CampaignObservation:
    """Build a renderer-neutral observation without mutating authoritative state."""

    viewer = None
    if viewer_id is not None:
        try:
            viewer = world.entities[viewer_id]
        except KeyError as exc:
            raise KeyError(f"unknown viewer: {viewer_id}") from exc

    area_id = viewer.position.area if viewer is not None else None
    knowledge = world.knowledge.get(viewer_id) if viewer_id is not None else None

    location: LocationObservation | None = None
    if area_id is not None:
        location_spec = content.locations.get(area_id)
        if location_spec is not None:
            exits: list[ExitObservation] = []
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
                    ExitObservation(
                        connection_id=connection.id,
                        destination_id=destination_id,
                        destination_name=destination.name if destination else destination_id,
                        travel_minutes=connection.travel_minutes,
                        hidden=connection.hidden,
                    )
                )
            location = LocationObservation(
                id=location_spec.id,
                name=location_spec.name,
                description=location_spec.description,
                region=location_spec.region,
                exits=exits,
                discovered_container_ids=(
                    sorted(
                        container_id
                        for container_id in knowledge.container_ids
                        if (
                            container_id in content.containers
                            and content.containers[container_id].location_id == area_id
                        )
                    )
                    if knowledge is not None
                    else []
                ),
            )

    visible_ids = sorted(world.entities)
    if viewer is not None and area_id is not None:
        visible_ids = sorted(
            entity.id
            for entity in world.entities.values()
            if entity.id == viewer.id or entity.position.area == area_id
        )

    encounters = []
    for encounter in sorted(world.encounters.values(), key=lambda item: item.id):
        if viewer_id is not None and viewer_id not in encounter.participant_ids:
            continue
        encounters.append(
            EncounterObservation(
                id=encounter.id,
                round=encounter.round,
                active_actor_id=encounter.active_actor_id,
                participant_ids=list(encounter.participant_ids),
                viewer_budget=(
                    encounter.budgets.get(viewer_id).model_copy(deep=True)
                    if viewer_id is not None and viewer_id in encounter.budgets
                    else None
                ),
            )
        )

    quests = []
    if viewer_id is not None:
        for progress in sorted(
            world.quest_progress.get(viewer_id, {}).values(), key=lambda item: item.quest_id
        ):
            spec = content.quests.get(progress.quest_id)
            quests.append(
                QuestObservation(
                    quest_id=progress.quest_id,
                    name=spec.name if spec else progress.quest_id,
                    state=progress.state,
                    completed=progress.completed,
                )
            )

    dialogues = []
    if viewer_id is not None:
        for session in sorted(world.dialogue_sessions.values(), key=lambda item: item.id):
            if session.actor_id != viewer_id:
                continue
            dialogues.append(
                DialogueObservation(
                    session_id=session.id,
                    npc_id=session.npc_id,
                    dialogue_id=session.dialogue_id,
                    node_id=session.node_id,
                    active=session.active,
                )
            )

    return CampaignObservation(
        campaign_id=world.campaign_id,
        sequence=world.sequence,
        time_minutes=world.time_minutes,
        viewer_id=viewer_id,
        location=location,
        actors=[_actor_observation(world, entity_id) for entity_id in visible_ids],
        encounters=encounters,
        quests=quests,
        dialogues=dialogues,
    )
