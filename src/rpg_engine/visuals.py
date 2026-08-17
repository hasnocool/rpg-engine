"""Renderer-neutral visual snapshots and non-authoritative presentation hints."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import Field

from rpg_engine.content.models import ContentRegistry
from rpg_engine.events import Event
from rpg_engine.models import Position, StrictModel, WorldState
from rpg_engine.observations import CampaignObservation, build_observation


class SceneBinding(StrictModel):
    scene_2d: str | None = None
    scene_3d: str | None = None
    terminal_title: str | None = None


class ActorBinding(StrictModel):
    scene_2d: str | None = None
    scene_3d: str | None = None
    terminal_glyph: str = "?"


class EventBinding(StrictModel):
    animation: str | None = None
    vfx_2d: str | None = None
    vfx_3d: str | None = None
    audio: str | None = None
    interpolation_ms: int = Field(default=250, ge=0, le=60_000)


class VisualBindingManifest(StrictModel):
    """Renderer-owned bindings. Paths are opaque to the authoritative simulation."""

    version: int = 1
    scenes: dict[str, SceneBinding] = Field(default_factory=dict)
    actor_tags: dict[str, ActorBinding] = Field(default_factory=dict)
    event_bindings: dict[str, EventBinding] = Field(default_factory=dict)


class VisualActor(StrictModel):
    entity_id: str
    name: str
    tags: set[str] = Field(default_factory=set)
    logical_position: Position
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    scene_2d: str | None = None
    scene_3d: str | None = None
    terminal_glyph: str = "?"


class VisualExit(StrictModel):
    connection_id: str
    destination_id: str
    destination_name: str
    travel_minutes: int


class VisualSnapshot(StrictModel):
    schema_version: Literal[1] = 1
    campaign_id: str
    sequence: int
    viewer_id: str | None = None
    location_id: str | None = None
    location_name: str | None = None
    scene_2d: str | None = None
    scene_3d: str | None = None
    terminal_title: str | None = None
    actors: list[VisualActor] = Field(default_factory=list)
    exits: list[VisualExit] = Field(default_factory=list)


class MovementInterpolationHint(StrictModel):
    type: Literal["movement_interpolation"] = "movement_interpolation"
    entity_id: str
    to_position: Position
    duration_ms: int = Field(default=250, ge=0, le=60_000)
    easing: str = "ease_in_out"


class AnimationHint(StrictModel):
    type: Literal["animation"] = "animation"
    entity_id: str
    animation: str


class VfxHint(StrictModel):
    type: Literal["vfx"] = "vfx"
    entity_id: str | None = None
    resource_2d: str | None = None
    resource_3d: str | None = None


class AudioHint(StrictModel):
    type: Literal["audio"] = "audio"
    entity_id: str | None = None
    resource: str


PresentationHint = Annotated[
    MovementInterpolationHint | AnimationHint | VfxHint | AudioHint,
    Field(discriminator="type"),
]


class PresentationBatch(StrictModel):
    event_sequence: int
    event_type: str
    hints: list[PresentationHint] = Field(default_factory=list)


def load_visual_bindings(path: Path) -> VisualBindingManifest:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected visual binding mapping in {path}")
    return VisualBindingManifest.model_validate(payload)


async def load_visual_bindings_async(path: Path) -> VisualBindingManifest:
    """Load renderer bindings without blocking an active event loop."""

    return await asyncio.to_thread(load_visual_bindings, path)


def _binding_for_actor(tags: set[str], bindings: VisualBindingManifest) -> ActorBinding:
    for tag in sorted(tags):
        binding = bindings.actor_tags.get(tag)
        if binding is not None:
            return binding
    return ActorBinding(terminal_glyph="@" if "hero" in tags else "n" if "npc" in tags else "?")


def visual_snapshot_from_observation(
    observation: CampaignObservation,
    bindings: VisualBindingManifest | None = None,
) -> VisualSnapshot:
    bindings = bindings or VisualBindingManifest()
    location_id = observation.location.id if observation.location is not None else None
    scene = bindings.scenes.get(location_id or "", SceneBinding())
    actors = []
    for actor in observation.actors:
        binding = _binding_for_actor(set(actor.tags), bindings)
        position = actor.position
        actors.append(
            VisualActor(
                entity_id=actor.id,
                name=actor.name,
                tags=set(actor.tags),
                logical_position=position.model_copy(deep=True),
                x=float(position.x or 0.0),
                y=float(position.y or 0.0),
                z=float(position.z or 0.0),
                scene_2d=binding.scene_2d,
                scene_3d=binding.scene_3d,
                terminal_glyph=binding.terminal_glyph[:1] or "?",
            )
        )
    exits = []
    if observation.location is not None:
        exits = [
            VisualExit(
                connection_id=item.connection_id,
                destination_id=item.destination_id,
                destination_name=item.destination_name,
                travel_minutes=item.travel_minutes,
            )
            for item in observation.location.exits
        ]
    return VisualSnapshot(
        campaign_id=observation.campaign_id,
        sequence=observation.sequence,
        viewer_id=observation.viewer_id,
        location_id=location_id,
        location_name=observation.location.name if observation.location is not None else None,
        scene_2d=scene.scene_2d,
        scene_3d=scene.scene_3d,
        terminal_title=scene.terminal_title,
        actors=actors,
        exits=exits,
    )


def build_visual_snapshot(
    world: WorldState,
    content: ContentRegistry,
    *,
    viewer_id: str | None = None,
    bindings: VisualBindingManifest | None = None,
) -> VisualSnapshot:
    observation = build_observation(world, content, viewer_id=viewer_id)
    return visual_snapshot_from_observation(observation, bindings)


def _event_entity_id(payload: dict[str, object]) -> str | None:
    for key in ("actor_id", "attacker_id", "target_id", "npc_id", "source_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    session = payload.get("session")
    if isinstance(session, dict):
        actor_id = session.get("actor_id")
        if isinstance(actor_id, str) and actor_id:
            return actor_id
    return None


def _default_binding(event_type: str) -> EventBinding:
    defaults = {
        "actor_moved": EventBinding(animation="walk", interpolation_ms=250),
        "travel_completed": EventBinding(animation="walk", interpolation_ms=400),
        "attack_rolled": EventBinding(animation="attack"),
        "damage_applied": EventBinding(animation="react"),
        "healing_applied": EventBinding(animation="recover"),
        "actor_defeated": EventBinding(animation="defeated"),
        "dialogue_started": EventBinding(animation="talk"),
        "item_equipped": EventBinding(animation="equip"),
    }
    return defaults.get(event_type, EventBinding())


def presentation_hints_for_event(
    event: Event,
    bindings: VisualBindingManifest | None = None,
) -> PresentationBatch:
    """Derive optional renderer hints without changing authoritative state or replay semantics."""

    bindings = bindings or VisualBindingManifest()
    payload = event.model_dump(mode="python")
    event_type = str(payload.get("type", "event"))
    binding = bindings.event_bindings.get(event_type, _default_binding(event_type))
    entity_id = _event_entity_id(payload)
    hints: list[PresentationHint] = []

    position_payload = payload.get("position")
    if event_type in {"actor_moved", "travel_completed"} and entity_id is not None:
        if isinstance(position_payload, Position):
            position = position_payload
        elif isinstance(position_payload, dict):
            position = Position.model_validate(position_payload)
        else:
            position = None
        if position is not None:
            hints.append(
                MovementInterpolationHint(
                    entity_id=entity_id,
                    to_position=position.model_copy(deep=True),
                    duration_ms=binding.interpolation_ms,
                )
            )

    if binding.animation and entity_id is not None:
        hints.append(AnimationHint(entity_id=entity_id, animation=binding.animation))
    if binding.vfx_2d or binding.vfx_3d:
        hints.append(
            VfxHint(
                entity_id=entity_id,
                resource_2d=binding.vfx_2d,
                resource_3d=binding.vfx_3d,
            )
        )
    if binding.audio:
        hints.append(AudioHint(entity_id=entity_id, resource=binding.audio))

    return PresentationBatch(
        event_sequence=event.sequence,
        event_type=event_type,
        hints=hints,
    )
