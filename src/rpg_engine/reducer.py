"""Event reducer for deterministic reconstruction between snapshots."""

from __future__ import annotations

from rpg_engine.events import (
    ActionBudgetSpentEvent,
    ActorMovedEvent,
    AiProposalActivatedEvent,
    AiProposalEvaluatedEvent,
    CalendarAdvancedEvent,
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
    DynamicQuestGeneratedEvent,
    DynamicQuestUpdatedEvent,
    EffectActivatedEvent,
    EffectDurationTickedEvent,
    EffectExpiredEvent,
    EncounterEndedEvent,
    EncounterStartedEvent,
    EntityCreatedEvent,
    Event,
    FactionRelationChangedEvent,
    HealingAppliedEvent,
    ItemEquippedEvent,
    ItemUnequippedEvent,
    LivingWorldInitializedEvent,
    LocationDiscoveredEvent,
    NpcMemoryForgottenEvent,
    NpcMemoryRecordedEvent,
    NpcScheduleAppliedEvent,
    NpcSpawnedEvent,
    OffscreenEncounterResolvedEvent,
    QuestAdvancedEvent,
    QuestStartedEvent,
    ReactionOfferedEvent,
    ReactionUsedEvent,
    ReputationChangedEvent,
    ResourceHarvestedEvent,
    ResourceNodeInitializedEvent,
    ResourceRegeneratedEvent,
    ResourceSpentEvent,
    RumorGeneratedEvent,
    SettlementEconomyTickedEvent,
    SettlementInitializedEvent,
    TimeAdvancedEvent,
    TimelineAdvancedEvent,
    TimelineConfiguredEvent,
    TimelineItemCancelledEvent,
    TimelineItemFiredEvent,
    TimelineItemScheduledEvent,
    TimelinePauseChangedEvent,
    TransactionCompletedEvent,
    TravelCompletedEvent,
    TriggerRaisedEvent,
    TurnStartedEvent,
    WeatherChangedEvent,
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
    elif isinstance(event, ItemEquippedEvent | ItemUnequippedEvent):
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
    elif isinstance(event, DamageAppliedEvent | HealingAppliedEvent):
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
    elif isinstance(event, TimelineConfiguredEvent):
        world.timeline.mode = event.mode
        world.timeline.turn_quantum_ms = event.turn_quantum_ms
        world.timeline.turn_timeout_ms = event.turn_timeout_ms
        world.timeline.paused = event.paused
        world.timeline.wall_clock_anchor_ms = event.wall_clock_anchor_ms
    elif isinstance(event, TimelineAdvancedEvent):
        world.timeline.now_ms = event.now_ms
        world.time_minutes = event.now_ms // 60_000
        world.timeline.wall_clock_anchor_ms = event.wall_clock_anchor_ms
    elif isinstance(event, TimelineItemScheduledEvent):
        world.timeline.queue[event.item.id] = event.item.model_copy(deep=True)
        world.timeline.next_order = max(world.timeline.next_order, event.item.order + 1)
    elif isinstance(event, TimelineItemFiredEvent):
        world.timeline.queue.pop(event.item.id, None)
        if event.rescheduled_item is not None:
            item = event.rescheduled_item.model_copy(deep=True)
            world.timeline.queue[item.id] = item
    elif isinstance(event, TimelineItemCancelledEvent):
        world.timeline.queue.pop(event.item_id, None)
    elif isinstance(event, TimelinePauseChangedEvent):
        world.timeline.paused = event.paused
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
        world.timeline.queue.pop(event.item.id, None)
        if event.rescheduled_item is not None:
            rescheduled = event.rescheduled_item.model_copy(deep=True)
            world.timeline.queue[rescheduled.id] = rescheduled
            world.timeline.next_order = max(world.timeline.next_order, rescheduled.order + 1)
    elif isinstance(event, TimelinePauseChangedEvent):
        world.timeline.paused = event.paused
    elif isinstance(event, LivingWorldInitializedEvent):
        world.living_world_initialized = True
    elif isinstance(event, CalendarAdvancedEvent):
        world.calendar = event.calendar.model_copy(deep=True)
    elif isinstance(event, WeatherChangedEvent):
        world.weather[event.weather.profile_id] = event.weather.model_copy(deep=True)
    elif isinstance(event, NpcScheduleAppliedEvent):
        state = event.schedule.model_copy(deep=True)
        world.npc_schedules[state.actor_id] = state
        actor = world.entities.get(state.actor_id)
        if actor is not None:
            actor.position = event.position.model_copy(deep=True)
    elif isinstance(event, FactionRelationChangedEvent):
        world.faction_relations.setdefault(event.faction_a_id, {})[
            event.faction_b_id
        ] = event.current
        world.faction_relations.setdefault(event.faction_b_id, {})[
            event.faction_a_id
        ] = event.current
    elif isinstance(event, ReputationChangedEvent):
        world.reputation.setdefault(event.actor_id, {})[event.faction_id] = event.current
    elif isinstance(event, SettlementInitializedEvent | SettlementEconomyTickedEvent):
        world.settlements[event.settlement.id] = event.settlement.model_copy(deep=True)
    elif isinstance(event, OffscreenEncounterResolvedEvent):
        record = event.record.model_copy(deep=True)
        world.offscreen_encounters[record.id] = record
        for actor_id, hp_after in record.health_after.items():
            actor = world.entities.get(actor_id)
            if actor is not None and actor.health is not None:
                actor.health.current = hp_after
    elif isinstance(event, RumorGeneratedEvent):
        world.rumors[event.rumor.id] = event.rumor.model_copy(deep=True)
    elif isinstance(event, DynamicQuestGeneratedEvent | DynamicQuestUpdatedEvent):
        world.dynamic_quests[event.quest.id] = event.quest.model_copy(deep=True)
        if (
            isinstance(event, DynamicQuestUpdatedEvent)
            and event.actor_id is not None
            and event.reward_currency is not None
            and event.actor_balance_after is not None
        ):
            actor = world.entities.get(event.actor_id)
            if actor is not None:
                actor.inventory.currency[event.reward_currency] = event.actor_balance_after
    elif isinstance(event, ResourceNodeInitializedEvent):
        world.resource_nodes[event.node.id] = event.node.model_copy(deep=True)
    elif isinstance(event, ResourceHarvestedEvent):
        node = world.resource_nodes[event.node_id]
        node.amount = event.node_amount_after
        actor = world.entities[event.actor_id]
        actor.inventory.item_ids = list(event.actor_item_ids_after)
    elif isinstance(event, ResourceRegeneratedEvent):
        node = world.resource_nodes[event.node_id]
        node.amount = event.amount_after
        node.last_regen_minute = event.last_regen_minute

    elif isinstance(event, NpcMemoryRecordedEvent):
        memory = event.memory.model_copy(deep=True)
        world.npc_memories.setdefault(memory.actor_id, {})[memory.id] = memory
    elif isinstance(event, NpcMemoryForgottenEvent):
        memories = world.npc_memories.get(event.actor_id)
        if memories is not None:
            memories.pop(event.memory_id, None)
            if not memories:
                world.npc_memories.pop(event.actor_id, None)
    elif isinstance(event, AiProposalEvaluatedEvent | AiProposalActivatedEvent):
        record = event.record.model_copy(deep=True)
        world.ai_proposals[record.id] = record

    world.rng_counters.clear()
    world.rng_counters.update(event.rng_counters_after)
    world.sequence = max(world.sequence, event.sequence)
    world.event_count = max(world.event_count, event.sequence)
