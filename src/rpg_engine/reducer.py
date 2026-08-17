"""Event reducer for deterministic reconstruction between snapshots."""

from __future__ import annotations

from rpg_engine.events import (
    ActionBudgetSpentEvent,
    ActorMovedEvent,
    ConcentrationEndedEvent,
    ConcentrationStartedEvent,
    ConditionAddedEvent,
    ConditionRemovedEvent,
    DamageAppliedEvent,
    EffectActivatedEvent,
    EffectDurationTickedEvent,
    EffectExpiredEvent,
    EncounterEndedEvent,
    EncounterStartedEvent,
    EntityCreatedEvent,
    Event,
    HealingAppliedEvent,
    ReactionOfferedEvent,
    ReactionUsedEvent,
    ResourceSpentEvent,
    TimeAdvancedEvent,
    TimelineAdvancedEvent,
    TimelineConfiguredEvent,
    TimelineItemCancelledEvent,
    TimelineItemFiredEvent,
    TimelineItemScheduledEvent,
    TimelinePauseChangedEvent,
    TriggerRaisedEvent,
    TurnStartedEvent,
)
from rpg_engine.models import ConcentrationState, ReactionWindow, WorldState


def apply_event(world: WorldState, event: Event) -> None:
    if isinstance(event, EntityCreatedEvent):
        world.entities[event.entity.id] = event.entity.model_copy(deep=True)
    elif isinstance(event, ActorMovedEvent):
        world.entities[event.actor_id].position = event.position.model_copy(deep=True)
    elif isinstance(event, (DamageAppliedEvent, HealingAppliedEvent)):
        health = world.entities[event.target_id].health
        if health is not None:
            health.current = event.hp_after
    elif isinstance(event, ConditionAddedEvent):
        world.entities[event.target_id].conditions.add(event.condition)
    elif isinstance(event, ConditionRemovedEvent):
        world.entities[event.target_id].conditions.discard(event.condition)
    elif isinstance(event, TimeAdvancedEvent):
        world.time_minutes = event.time_minutes
    elif isinstance(event, EncounterStartedEvent):
        world.encounters[event.encounter.id] = event.encounter.model_copy(deep=True)
    elif isinstance(event, EncounterEndedEvent):
        encounter = world.encounters.get(event.encounter_id)
        if encounter is not None:
            encounter.active = False
        world.reaction_windows = {
            trigger_id: window
            for trigger_id, window in world.reaction_windows.items()
            if not any(offer.actor_id in event.participant_ids for offer in window.offers)
        }
    elif isinstance(event, TurnStartedEvent):
        encounter = world.encounters[event.encounter_id]
        encounter.round = event.round
        encounter.turn_index = event.turn_index
        encounter.budgets[event.actor_id] = event.budget.model_copy(deep=True)
    elif isinstance(event, ActionBudgetSpentEvent):
        budget = world.encounters[event.encounter_id].budgets[event.actor_id]
        setattr(budget, event.budget_kind, event.remaining)
    elif isinstance(event, ResourceSpentEvent):
        world.entities[event.actor_id].resources[event.resource_id].current = event.remaining
    elif isinstance(event, EffectActivatedEvent):
        world.active_effects[event.effect.instance_id] = event.effect.model_copy(deep=True)
    elif isinstance(event, EffectDurationTickedEvent):
        active = world.active_effects.get(event.effect_instance_id)
        if active is not None:
            active.remaining_turns = event.remaining_turns
    elif isinstance(event, EffectExpiredEvent):
        world.active_effects.pop(event.effect_instance_id, None)
    elif isinstance(event, ConcentrationStartedEvent):
        world.entities[event.actor_id].concentration = ConcentrationState(
            effect_instance_id=event.effect_instance_id,
            effect_id=event.effect_id,
        )
    elif isinstance(event, ConcentrationEndedEvent):
        actor = world.entities[event.actor_id]
        if (
            actor.concentration
            and actor.concentration.effect_instance_id == event.effect_instance_id
        ):
            actor.concentration = None
    elif isinstance(event, TriggerRaisedEvent):
        world.reaction_windows[event.trigger_id] = ReactionWindow(
            trigger_id=event.trigger_id,
            kind=event.kind,
            source_id=event.source_id,
            target_id=event.target_id,
        )
    elif isinstance(event, ReactionOfferedEvent):
        window = world.reaction_windows.get(event.offer.trigger_id)
        if window is not None:
            window.offers.append(event.offer.model_copy(deep=True))
    elif isinstance(event, ReactionUsedEvent):
        window = world.reaction_windows.get(event.trigger_id)
        if window is not None:
            window.offers = [
                offer
                for offer in window.offers
                if not (offer.actor_id == event.actor_id and offer.reaction_id == event.reaction_id)
            ]
            if not window.offers:
                world.reaction_windows.pop(event.trigger_id, None)
    elif isinstance(event, TimelineConfiguredEvent):
        if not event.paused and world.timeline.paused:
            world.timeline.paused = False
        world.timeline.mode = event.mode
        world.timeline.turn_quantum_ms = event.turn_quantum_ms
        world.timeline.turn_timeout_ms = event.turn_timeout_ms
        world.timeline.paused = event.paused
        world.timeline.wall_clock_anchor_ms = event.wall_clock_anchor_ms
    elif isinstance(event, TimelineItemScheduledEvent):
        item = event.item.model_copy(deep=True)
        world.timeline.queue[item.id] = item
        world.timeline.next_order = max(world.timeline.next_order, item.order + 1)
    elif isinstance(event, TimelineItemCancelledEvent):
        world.timeline.queue.pop(event.item_id, None)
    elif isinstance(event, TimelineAdvancedEvent):
        world.timeline.now_ms = event.time_ms
        world.timeline.wall_clock_anchor_ms = event.wall_clock_anchor_ms
        world.time_minutes = event.time_ms // 60_000
    elif isinstance(event, TimelineItemFiredEvent):
        if event.rescheduled_item is None:
            world.timeline.queue.pop(event.item.id, None)
        else:
            replacement = event.rescheduled_item.model_copy(deep=True)
            world.timeline.queue[replacement.id] = replacement
    elif isinstance(event, TimelinePauseChangedEvent):
        world.timeline.paused = event.paused

    world.rng_counters.clear()
    world.rng_counters.update(event.rng_counters_after)
    world.sequence = max(world.sequence, event.sequence)
    world.event_count = max(world.event_count, event.sequence)
