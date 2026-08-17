"""Visual snapshot, presentation-hint, and terminal renderer regressions."""

from rpg_engine.content.models import ContentRegistry, WorldConnectionSpec, WorldLocationSpec
from rpg_engine.events import ActorMovedEvent
from rpg_engine.models import AdventureKnowledge, Entity, Identity, Position, WorldState
from rpg_engine.terminal_visual import render_visual_snapshot
from rpg_engine.visuals import (
    ActorBinding,
    SceneBinding,
    VisualBindingManifest,
    build_visual_snapshot,
    presentation_hints_for_event,
)


def _world_and_content() -> tuple[WorldState, ContentRegistry]:
    world = WorldState(campaign_id="visual", seed=7)
    world.entities["hero"] = Entity(
        id="hero",
        identity=Identity(name="Hero", tags={"hero", "humanoid"}),
        position=Position(area="village", x=2, y=1),
    )
    world.knowledge["hero"] = AdventureKnowledge(location_ids={"village"})
    content = ContentRegistry.with_core_defaults()
    content.locations["village"] = WorldLocationSpec(id="village", name="Village")
    content.locations["forest"] = WorldLocationSpec(id="forest", name="Forest")
    content.locations["ruins"] = WorldLocationSpec(id="ruins", name="Ruins")
    content.connections["road"] = WorldConnectionSpec(
        id="road",
        from_location_id="village",
        to_location_id="forest",
        travel_minutes=20,
    )
    content.connections["secret"] = WorldConnectionSpec(
        id="secret",
        from_location_id="village",
        to_location_id="ruins",
        travel_minutes=10,
        hidden=True,
    )
    return world, content


def test_visual_snapshot_uses_viewer_visibility_and_bindings() -> None:
    world, content = _world_and_content()
    bindings = VisualBindingManifest(
        scenes={
            "village": SceneBinding(
                scene_2d="res://world/village_2d.tscn",
                scene_3d="res://world/village_3d.tscn",
                terminal_title="Riverdale",
            )
        },
        actor_tags={
            "hero": ActorBinding(
                scene_2d="res://actors/hero_2d.tscn",
                scene_3d="res://actors/hero_3d.tscn",
                terminal_glyph="@",
            )
        },
    )

    snapshot = build_visual_snapshot(world, content, viewer_id="hero", bindings=bindings)

    assert snapshot.scene_2d == "res://world/village_2d.tscn"
    assert snapshot.scene_3d == "res://world/village_3d.tscn"
    assert snapshot.terminal_title == "Riverdale"
    assert snapshot.actors[0].terminal_glyph == "@"
    assert snapshot.actors[0].x == 2
    assert [item.destination_id for item in snapshot.exits] == ["forest"]


def test_presentation_hints_are_derived_from_event_without_mutating_it() -> None:
    event = ActorMovedEvent(
        sequence=12,
        campaign_id="visual",
        actor_id="hero",
        position=Position(area="village", x=4, y=3),
    )
    before = event.model_copy(deep=True)

    batch = presentation_hints_for_event(event)

    assert batch.event_sequence == 12
    assert [hint.type for hint in batch.hints] == ["movement_interpolation", "animation"]
    movement = batch.hints[0]
    assert movement.type == "movement_interpolation"
    assert movement.entity_id == "hero"
    assert movement.to_position.x == 4
    assert event == before


def test_terminal_visual_renders_same_snapshot_contract() -> None:
    world, content = _world_and_content()
    snapshot = build_visual_snapshot(world, content, viewer_id="hero")

    rendered = render_visual_snapshot(snapshot)

    assert "[Village]" in rendered
    assert "[Forest]" in rendered
    assert "Hero" in rendered
    assert "sequence=0 campaign=visual" in rendered
