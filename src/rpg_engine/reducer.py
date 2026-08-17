"""Event reducer for deterministic reconstruction between snapshots."""

from __future__ import annotations

from rpg_engine.events import (
    ActionBudgetSpentEvent,
    ActorMovedEvent,
    ConcentrationEndedEvent,
    ConcentrationStartedEvent,
    ConditionAddedEvent,
    ConditionRemovedEvent,
    ContainerCreatedEvent,
    ContainerLootedEvent,
    DamageAppliedEvent,
    DialogueAdvancedEvent,
    DialogueEndedEvent,
    DialogueStartedEvent,
    DiscoveryRevealedEvent,
    EffectActivatedEvent,
    EffectDurationTickedEvent,
    EffectExpiredEvent,
    EncounterEndedEvent,
    EncounterStartedEvent,
    EntityCreatedEvent,
    Event,
    HealingAppliedEvent,
    ItemEquippedEvent,
    ItemUnequippedEvent,
    LocationDiscoveredEvent,
    NpcSpawnedEvent,
    QuestAdvancedEvent,
    QuestStartedEvent,
    ReactionOfferedEvent,
    ReactionUsedEvent,
    ResourceSpentEvent,
    TimeAdvancedEvent,
    TransactionCompletedEvent,
    TravelCompletedEvent,
    TriggerRaisedEvent,
    TurnStartedEvent,
)
from rpg_engine.models import AdventureKnowledge, ConcentrationState, ReactionWindow, WorldState


def apply_event(world: WorldState, event: Event) -> None:
    if isinstance(event, EntityCreatedEvent):
        world.entities[event.entity.id] = event.entity.model_copy(deep=True)
    elif isinstance(event, NpcSpawnedEvent):
        world.entities[event.entity.id] = event.entity.model_copy(deep=True)
        world.entity_templates[event.entity.id] = event.template_id
    elif isinstance(event, LocationDiscoveredEvent):
        knowledge = world.knowledge.setdefault(event.actor_id, AdventureKnowledge())
        knowledge.location_ids.add(event.location_id)
    elif isinstance(event, DiscoveryRevealedEvent):
        knowledge = world.knowledge.setdefault(event.actor_id, AdventureKnowledge())
        knowledge.discovery_ids.add(event.discovery_id)
        knowledge.location_ids.update(event.location_ids)
        knowledge.connection_ids.update(event.connection_ids)
        knowledge.container_ids.update(event.container_ids)
    elif isinstance(event, TravelCompletedEvent):
        world.entities[event.actor_id].position = event.position.model_copy(deep=True)
        world.time_minutes = event.time_minutes
    elif isinstance(event, ContainerCreatedEvent):
        world.containers[event.container.id] = event.container.model_copy(deep=True)
    elif isinstance(event, ContainerLootedEvent):
        actor = world.entities[event.actor_id]
        container = world.containers[event.container_id]
        actor.inventory.item_ids = list(event.actor_item_ids_after)
        actor.inventory.currency = dict(event.actor_currency_after)
        container.item_ids = list(event.container_item_ids_after)
        container.currency = dict(event.container_currency_after)
    elif isinstance(event, (ItemEquippedEvent, ItemUnequippedEvent)):
        inventory = world.entities[event.actor_id].inventory
        inventory.equipment = dict(event.equipment_after)
        inventory.equipped_item_ids = list(event.equipped_item_ids_after)
    elif isinstance(event, DialogueStartedEvent):
        world.dialogue_sessions[event.session.id] = event.session.model_copy(deep=True)
    elif isinstance(event, DialogueAdvancedEvent):
        session = world.dialogue_sessions.get(event.session_id)
        if session is not None:
            session.node_id = event.to_node_id
    elif isinstance(event, DialogueEndedEvent):
        session = world.dialogue_sessions.get(event.session_id)
        if session is not None:
            session.active = False
    elif isinstance(event, QuestStartedEvent):
        world.quest_progress.setdefault(event.actor_id, {})[event.progress.quest_id] = (
            event.progress.model_copy(deep=True)
        )
    elif isinstance(event, QuestAdvancedEvent):
        progress = world.quest_progress.setdefault(event.actor_id, {}).get(event.quest_id)
        if progress is not None:
            progress.state = event.to_state
            progress.completed = event.completed
    elif isinstance(event, TransactionCompletedEvent):
        buyer = world.entities[event.buyer_id]
        seller = world.entities[event.seller_id]
        buyer.inventory.item_ids = list(event.buyer_item_ids_after)
        seller.inventory.item_ids = list(event.seller_item_ids_after)
        buyer.inventory.currency[event.currency] = event.buyer_balance_after
        seller.inventory.currency[event.currency] = event.seller_balance_after
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

    world.rng_counters.clear()
    world.rng_counters.update(event.rng_counters_after)
    world.sequence = max(world.sequence, event.sequence)
    world.event_count = max(world.event_count, event.sequence)
