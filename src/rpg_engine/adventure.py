"""Authoritative v0.3 adventure systems layered on the deterministic simulation core."""

from __future__ import annotations

from collections import Counter

from rpg_engine.commands import (
    AdvanceQuestCommand,
    BuyItemCommand,
    ChooseDialogueOptionCommand,
    Command,
    EquipItemCommand,
    ExploreLocationCommand,
    LootContainerCommand,
    SearchLocationCommand,
    SellItemCommand,
    SpawnNpcCommand,
    StartDialogueCommand,
    StartQuestCommand,
    TravelCommand,
    UnequipItemCommand,
)
from rpg_engine.content.models import (
    ContentRegistry,
    DiscoverySpec,
    MerchantSpec,
    QuestActionSpec,
)
from rpg_engine.dice import DeterministicRNG
from rpg_engine.events import (
    CheckRolledEvent,
    ContainerCreatedEvent,
    ContainerLootedEvent,
    DialogueAdvancedEvent,
    DialogueEndedEvent,
    DialogueStartedEvent,
    DiscoveryRevealedEvent,
    EventBase,
    ItemEquippedEvent,
    ItemUnequippedEvent,
    LocationDiscoveredEvent,
    LocationExploredEvent,
    LocationSearchedEvent,
    NpcSpawnedEvent,
    QuestAdvancedEvent,
    QuestStartedEvent,
    TransactionCompletedEvent,
    TravelCompletedEvent,
)
from rpg_engine.models import (
    AdventureKnowledge,
    ContainerState,
    DialogueSession,
    Entity,
    Position,
    QuestProgress,
    WorldState,
)
from rpg_engine.resolution import ModifierPipeline, ResolutionContext, ResolutionKind
from rpg_engine.rules.base import RulesRuntime


class AdventureError(ValueError):
    """Rejected adventure-layer command."""


class AdventureRuntime:
    """Data-driven world, exploration, dialogue, quest, inventory, and economy authority."""

    def __init__(
        self,
        world: WorldState,
        *,
        content: ContentRegistry,
        rules: RulesRuntime,
        rng: DeterministicRNG,
    ) -> None:
        self.world = world
        self.content = content
        self.rules = rules
        self.rng = rng
        self.modifiers = ModifierPipeline()

    @staticmethod
    def handles(command: Command) -> bool:
        return isinstance(
            command,
            SpawnNpcCommand
            | ExploreLocationCommand
            | SearchLocationCommand
            | TravelCommand
            | LootContainerCommand
            | EquipItemCommand
            | UnequipItemCommand
            | StartDialogueCommand
            | ChooseDialogueOptionCommand
            | StartQuestCommand
            | AdvanceQuestCommand
            | BuyItemCommand
            | SellItemCommand,
        )

    def _entity(self, entity_id: str) -> Entity:
        try:
            return self.world.entities[entity_id]
        except KeyError as exc:
            raise AdventureError(f"unknown entity: {entity_id}") from exc

    def _knowledge(self, actor_id: str) -> AdventureKnowledge:
        return self.world.knowledge.setdefault(actor_id, AdventureKnowledge())

    def _current_location(self, actor: Entity) -> str:
        if not actor.position.area:
            raise AdventureError(f"actor {actor.id!r} has no logical area/location")
        if actor.position.area not in self.content.locations:
            raise AdventureError(f"unknown world location: {actor.position.area}")
        return actor.position.area

    def _require_out_of_encounter(self, actor_id: str) -> None:
        if any(
            encounter.active and actor_id in encounter.participant_ids
            for encounter in self.world.encounters.values()
        ):
            raise AdventureError("adventure action is unavailable during an active encounter")

    def _require_colocated(self, first: Entity, second: Entity) -> None:
        if self._current_location(first) != self._current_location(second):
            raise AdventureError("actors must be in the same location")

    def _instantiate_container(self, container_id: str) -> tuple[ContainerState, list[EventBase]]:
        existing = self.world.containers.get(container_id)
        if existing is not None:
            return existing, []
        try:
            template = self.content.containers[container_id]
        except KeyError as exc:
            raise AdventureError(f"unknown container: {container_id}") from exc
        container = ContainerState(
            id=template.id,
            name=template.name,
            location_id=template.location_id,
            item_ids=list(template.item_ids),
            currency=dict(template.currency),
            locked=template.locked,
        )
        self.world.containers[container.id] = container
        return container, [ContainerCreatedEvent(container=container.model_copy(deep=True))]

    def _discover_location(self, actor_id: str, location_id: str) -> list[EventBase]:
        knowledge = self._knowledge(actor_id)
        if location_id in knowledge.location_ids:
            return []
        if location_id not in self.content.locations:
            raise AdventureError(f"unknown world location: {location_id}")
        knowledge.location_ids.add(location_id)
        return [LocationDiscoveredEvent(actor_id=actor_id, location_id=location_id)]

    def _reveal_discovery(self, actor_id: str, discovery: DiscoverySpec) -> list[EventBase]:
        knowledge = self._knowledge(actor_id)
        if discovery.id in knowledge.discovery_ids:
            return []
        knowledge.discovery_ids.add(discovery.id)
        knowledge.location_ids.update(discovery.reveal_location_ids)
        knowledge.connection_ids.update(discovery.reveal_connection_ids)
        knowledge.container_ids.update(discovery.reveal_container_ids)
        events: list[EventBase] = [
            DiscoveryRevealedEvent(
                actor_id=actor_id,
                discovery_id=discovery.id,
                location_ids=list(discovery.reveal_location_ids),
                connection_ids=list(discovery.reveal_connection_ids),
                container_ids=list(discovery.reveal_container_ids),
            )
        ]
        for container_id in discovery.reveal_container_ids:
            _, created = self._instantiate_container(container_id)
            events.extend(created)
        return events

    def _spawn_npc(self, command: SpawnNpcCommand) -> list[EventBase]:
        if command.entity_id in self.world.entities:
            raise AdventureError(f"entity already exists: {command.entity_id}")
        try:
            template = self.content.npc_templates[command.template_id]
        except KeyError as exc:
            raise AdventureError(f"unknown NPC template: {command.template_id}") from exc
        try:
            location = self.content.locations[command.location_id]
        except KeyError as exc:
            raise AdventureError(f"unknown world location: {command.location_id}") from exc
        entity = template.entity.model_copy(deep=True)
        entity.id = command.entity_id
        entity.position = Position(
            world=entity.position.world,
            region=location.region,
            area=location.id,
        )
        if template.merchant_id:
            try:
                merchant = self.content.merchants[template.merchant_id]
            except KeyError as exc:
                raise AdventureError(f"unknown merchant profile: {template.merchant_id}") from exc
            entity.inventory.item_ids.extend(merchant.stock_item_ids)
            entity.inventory.currency[merchant.currency] = (
                entity.inventory.currency.get(merchant.currency, 0) + merchant.funds
            )
        self.world.entities[entity.id] = entity
        self.world.entity_templates[entity.id] = template.id
        return [NpcSpawnedEvent(template_id=template.id, entity=entity.model_copy(deep=True))]

    def _explore(self, command: ExploreLocationCommand) -> list[EventBase]:
        self._require_out_of_encounter(command.actor_id)
        actor = self._entity(command.actor_id)
        location_id = self._current_location(actor)
        events = self._discover_location(actor.id, location_id)
        events.append(LocationExploredEvent(actor_id=actor.id, location_id=location_id))
        for discovery in sorted(self.content.discoveries.values(), key=lambda item: item.id):
            if discovery.location_id == location_id and discovery.dc == 0:
                events.extend(self._reveal_discovery(actor.id, discovery))
        return events

    def _search(self, command: SearchLocationCommand) -> list[EventBase]:
        self._require_out_of_encounter(command.actor_id)
        actor = self._entity(command.actor_id)
        location_id = self._current_location(actor)
        outcome = self.modifiers.resolve_d20(
            context=ResolutionContext(
                kind=ResolutionKind.CHECK,
                actor_id=actor.id,
                ability=command.ability,
            ),
            modifiers=self.rules.check_modifiers(actor, command.ability),
            rng=self.rng,
            stream=f"adventure:search:{actor.id}:{location_id}:{command.ability.value}",
        )
        events: list[EventBase] = [
            LocationSearchedEvent(
                actor_id=actor.id,
                location_id=location_id,
                ability=command.ability,
                die_roll=outcome.die_roll,
                modifier=outcome.modifier_total,
                modifiers=outcome.modifiers,
                total=outcome.total,
            )
        ]
        knowledge = self._knowledge(actor.id)
        for discovery in sorted(self.content.discoveries.values(), key=lambda item: item.id):
            if (
                discovery.location_id == location_id
                and discovery.ability == command.ability
                and discovery.id not in knowledge.discovery_ids
                and outcome.total >= discovery.dc
            ):
                events.extend(self._reveal_discovery(actor.id, discovery))
        return events

    def _travel(self, command: TravelCommand) -> list[EventBase]:
        self._require_out_of_encounter(command.actor_id)
        actor = self._entity(command.actor_id)
        source_id = self._current_location(actor)
        if command.destination_id not in self.content.locations:
            raise AdventureError(f"unknown destination: {command.destination_id}")
        knowledge = self._knowledge(actor.id)
        candidates = [
            connection
            for connection in self.content.connections.values()
            if connection.connects(source_id, command.destination_id)
            and (not connection.hidden or connection.id in knowledge.connection_ids)
        ]
        if not candidates:
            raise AdventureError("no known traversable connection to destination")
        connection = min(candidates, key=lambda item: (item.travel_minutes, item.id))
        destination = self.content.locations[command.destination_id]
        actor.position = Position(
            world=actor.position.world,
            region=destination.region,
            area=destination.id,
        )
        self.world.time_minutes += connection.travel_minutes
        events: list[EventBase] = [
            TravelCompletedEvent(
                actor_id=actor.id,
                connection_id=connection.id,
                from_location_id=source_id,
                to_location_id=destination.id,
                minutes=connection.travel_minutes,
                position=actor.position.model_copy(deep=True),
                time_minutes=self.world.time_minutes,
            )
        ]
        events.extend(self._discover_location(actor.id, destination.id))
        return events

    def _loot(self, command: LootContainerCommand) -> list[EventBase]:
        self._require_out_of_encounter(command.actor_id)
        actor = self._entity(command.actor_id)
        location_id = self._current_location(actor)
        knowledge = self._knowledge(actor.id)
        if command.container_id not in knowledge.container_ids:
            raise AdventureError("container has not been discovered")
        container, events = self._instantiate_container(command.container_id)
        if container.locked:
            raise AdventureError("container is locked")
        if container.location_id and container.location_id != location_id:
            raise AdventureError("container is not in the actor's location")
        requested = list(container.item_ids) if command.item_ids is None else list(command.item_ids)
        available = Counter(container.item_ids)
        wanted = Counter(requested)
        if any(wanted[item_id] > available[item_id] for item_id in wanted):
            raise AdventureError("container does not contain requested item quantity")
        for item_id in requested:
            container.item_ids.remove(item_id)
            actor.inventory.item_ids.append(item_id)
        transferred_currency: dict[str, int] = {}
        if command.take_currency:
            transferred_currency = dict(container.currency)
            for currency, amount in transferred_currency.items():
                actor.inventory.currency[currency] = (
                    actor.inventory.currency.get(currency, 0) + amount
                )
            container.currency.clear()
        events.append(
            ContainerLootedEvent(
                actor_id=actor.id,
                container_id=container.id,
                item_ids=requested,
                currency=transferred_currency,
                actor_item_ids_after=list(actor.inventory.item_ids),
                actor_currency_after=dict(actor.inventory.currency),
                container_item_ids_after=list(container.item_ids),
                container_currency_after=dict(container.currency),
            )
        )
        return events

    def _equip(self, command: EquipItemCommand) -> list[EventBase]:
        self._require_out_of_encounter(command.actor_id)
        actor = self._entity(command.actor_id)
        if command.item_id not in actor.inventory.item_ids:
            raise AdventureError("actor does not own item")
        try:
            item = self.content.items[command.item_id]
        except KeyError as exc:
            raise AdventureError(f"unknown item: {command.item_id}") from exc
        if not item.equip_slot:
            raise AdventureError("item is not equippable")
        events: list[EventBase] = []
        previous = actor.inventory.equipment.get(item.equip_slot)
        if previous and previous != item.id:
            actor.inventory.equipment.pop(item.equip_slot, None)
            actor.inventory.equipped_item_ids = [
                item_id for item_id in actor.inventory.equipped_item_ids if item_id != previous
            ]
            events.append(
                ItemUnequippedEvent(
                    actor_id=actor.id,
                    item_id=previous,
                    slot=item.equip_slot,
                    equipment_after=dict(actor.inventory.equipment),
                    equipped_item_ids_after=list(actor.inventory.equipped_item_ids),
                )
            )
        actor.inventory.equipment[item.equip_slot] = item.id
        if item.id not in actor.inventory.equipped_item_ids:
            actor.inventory.equipped_item_ids.append(item.id)
        events.append(
            ItemEquippedEvent(
                actor_id=actor.id,
                item_id=item.id,
                slot=item.equip_slot,
                equipment_after=dict(actor.inventory.equipment),
                equipped_item_ids_after=list(actor.inventory.equipped_item_ids),
            )
        )
        return events

    def _unequip(self, command: UnequipItemCommand) -> list[EventBase]:
        self._require_out_of_encounter(command.actor_id)
        actor = self._entity(command.actor_id)
        slot = next(
            (
                slot
                for slot, item_id in actor.inventory.equipment.items()
                if item_id == command.item_id
            ),
            None,
        )
        if slot is None:
            raise AdventureError("item is not equipped")
        actor.inventory.equipment.pop(slot, None)
        actor.inventory.equipped_item_ids = [
            item_id for item_id in actor.inventory.equipped_item_ids if item_id != command.item_id
        ]
        return [
            ItemUnequippedEvent(
                actor_id=actor.id,
                item_id=command.item_id,
                slot=slot,
                equipment_after=dict(actor.inventory.equipment),
                equipped_item_ids_after=list(actor.inventory.equipped_item_ids),
            )
        ]

    def _start_quest(
        self, actor_id: str, quest_id: str, *, allow_existing: bool
    ) -> list[EventBase]:
        self._entity(actor_id)
        try:
            quest = self.content.quests[quest_id]
        except KeyError as exc:
            raise AdventureError(f"unknown quest: {quest_id}") from exc
        actor_quests = self.world.quest_progress.setdefault(actor_id, {})
        if quest_id in actor_quests:
            if allow_existing:
                return []
            raise AdventureError("quest has already started")
        progress = QuestProgress(
            quest_id=quest.id,
            state=quest.initial_state,
            started_by=actor_id,
            completed=quest.initial_state in quest.terminal_states,
        )
        actor_quests[quest.id] = progress
        return [QuestStartedEvent(actor_id=actor_id, progress=progress.model_copy(deep=True))]

    def _advance_quest(self, actor_id: str, quest_id: str, trigger: str) -> list[EventBase]:
        self._entity(actor_id)
        try:
            quest = self.content.quests[quest_id]
        except KeyError as exc:
            raise AdventureError(f"unknown quest: {quest_id}") from exc
        progress = self.world.quest_progress.get(actor_id, {}).get(quest_id)
        if progress is None:
            raise AdventureError("quest has not started")
        if progress.completed:
            raise AdventureError("quest is already complete")
        transition = next(
            (
                candidate
                for candidate in quest.transitions
                if candidate.from_state == progress.state and candidate.trigger == trigger
            ),
            None,
        )
        if transition is None:
            raise AdventureError("quest trigger is invalid for the current state")
        old_state = progress.state
        progress.state = transition.to_state
        progress.completed = progress.state in quest.terminal_states
        return [
            QuestAdvancedEvent(
                actor_id=actor_id,
                quest_id=quest.id,
                trigger=trigger,
                from_state=old_state,
                to_state=progress.state,
                completed=progress.completed,
            )
        ]

    def _apply_quest_action(self, actor_id: str, action: QuestActionSpec) -> list[EventBase]:
        if action.type == "start":
            return self._start_quest(actor_id, action.quest_id, allow_existing=True)
        assert action.trigger is not None
        return self._advance_quest(actor_id, action.quest_id, action.trigger)

    def _dialogue_id_for_npc(self, npc_id: str, explicit: str | None) -> str:
        if explicit:
            return explicit
        template_id = self.world.entity_templates.get(npc_id)
        if template_id is None:
            raise AdventureError("NPC has no content template binding")
        template = self.content.npc_templates.get(template_id)
        if template is None or template.dialogue_id is None:
            raise AdventureError("NPC has no dialogue")
        return template.dialogue_id

    def _start_dialogue(self, command: StartDialogueCommand) -> list[EventBase]:
        self._require_out_of_encounter(command.actor_id)
        actor = self._entity(command.actor_id)
        npc = self._entity(command.npc_id)
        self._require_colocated(actor, npc)
        dialogue_id = self._dialogue_id_for_npc(npc.id, command.dialogue_id)
        try:
            dialogue = self.content.dialogues[dialogue_id]
        except KeyError as exc:
            raise AdventureError(f"unknown dialogue: {dialogue_id}") from exc
        session_id = f"{dialogue.id}:{actor.id}:{npc.id}:{self.world.sequence + 1}"
        session = DialogueSession(
            id=session_id,
            actor_id=actor.id,
            npc_id=npc.id,
            dialogue_id=dialogue.id,
            node_id=dialogue.start_node_id,
        )
        self.world.dialogue_sessions[session.id] = session
        return [DialogueStartedEvent(session=session.model_copy(deep=True))]

    def _choose_dialogue(self, command: ChooseDialogueOptionCommand) -> list[EventBase]:
        self._require_out_of_encounter(command.actor_id)
        session = self.world.dialogue_sessions.get(command.session_id)
        if session is None or not session.active:
            raise AdventureError("dialogue session is not active")
        if session.actor_id != command.actor_id:
            raise AdventureError("dialogue session belongs to another actor")
        actor = self._entity(session.actor_id)
        npc = self._entity(session.npc_id)
        self._require_colocated(actor, npc)
        dialogue = self.content.dialogues[session.dialogue_id]
        node = dialogue.nodes[session.node_id]
        option = next((item for item in node.options if item.id == command.option_id), None)
        if option is None:
            raise AdventureError("unknown dialogue option")
        actor_quests = self.world.quest_progress.get(actor.id, {})
        for quest_id, allowed_states in option.requires_quest_states.items():
            progress = actor_quests.get(quest_id)
            if progress is None or progress.state not in allowed_states:
                raise AdventureError("dialogue option requirements are not met")

        events: list[EventBase] = []
        destination_id = option.next_node_id
        if option.check is not None:
            outcome = self.modifiers.resolve_d20(
                context=ResolutionContext(
                    kind=ResolutionKind.CHECK,
                    actor_id=actor.id,
                    target_id=npc.id,
                    ability=option.check.ability,
                    dc=option.check.dc,
                    tags={f"dialogue:{dialogue.id}", f"option:{option.id}"},
                ),
                modifiers=self.rules.check_modifiers(actor, option.check.ability),
                rng=self.rng,
                stream=f"dialogue:{dialogue.id}:{session.id}:{option.id}",
            )
            events.append(
                CheckRolledEvent(
                    actor_id=actor.id,
                    ability=option.check.ability,
                    dc=option.check.dc,
                    die_roll=outcome.die_roll,
                    modifier=outcome.modifier_total,
                    modifiers=outcome.modifiers,
                    total=outcome.total,
                    success=bool(outcome.success),
                )
            )
            destination_id = (
                option.success_node_id if outcome.success else option.failure_node_id
            ) or option.next_node_id

        if destination_id is not None and destination_id not in dialogue.nodes:
            raise AdventureError("dialogue option points to an unknown node")

        for action in option.quest_actions:
            events.extend(self._apply_quest_action(actor.id, action))

        old_node = session.node_id
        should_end = option.end_dialogue or destination_id is None
        if destination_id is not None:
            session.node_id = destination_id
            events.append(
                DialogueAdvancedEvent(
                    session_id=session.id,
                    option_id=option.id,
                    from_node_id=old_node,
                    to_node_id=destination_id,
                )
            )
        if should_end:
            session.active = False
            events.append(
                DialogueEndedEvent(
                    session_id=session.id,
                    actor_id=actor.id,
                    npc_id=npc.id,
                )
            )
        return events

    def _merchant_profile(self, merchant_id: str) -> tuple[Entity, MerchantSpec]:
        merchant = self._entity(merchant_id)
        template_id = self.world.entity_templates.get(merchant.id)
        if template_id is None:
            raise AdventureError("merchant has no NPC template binding")
        template = self.content.npc_templates.get(template_id)
        if template is None or template.merchant_id is None:
            raise AdventureError("NPC is not a merchant")
        try:
            profile = self.content.merchants[template.merchant_id]
        except KeyError as exc:
            raise AdventureError("merchant profile is missing") from exc
        return merchant, profile

    def _price(self, item_id: str, profile: MerchantSpec, *, merchant_sells: bool) -> int:
        try:
            item = self.content.items[item_id]
        except KeyError as exc:
            raise AdventureError(f"unknown item: {item_id}") from exc
        base = profile.price_overrides.get(item_id, item.value)
        multiplier = profile.sell_multiplier if merchant_sells else profile.buy_multiplier
        return max(0, int(base * multiplier))

    def _transaction(
        self,
        *,
        buyer: Entity,
        seller: Entity,
        profile: MerchantSpec,
        item_id: str,
        quantity: int,
        merchant_sells: bool,
    ) -> list[EventBase]:
        available = seller.inventory.item_ids.count(item_id)
        equipped = seller.inventory.equipped_item_ids.count(item_id)
        if available - equipped < quantity:
            raise AdventureError("seller does not have enough unequipped stock")
        unit_price = self._price(item_id, profile, merchant_sells=merchant_sells)
        total = unit_price * quantity
        currency = profile.currency
        buyer_balance = buyer.inventory.currency.get(currency, 0)
        if buyer_balance < total:
            raise AdventureError("buyer has insufficient currency")
        for _ in range(quantity):
            seller.inventory.item_ids.remove(item_id)
            buyer.inventory.item_ids.append(item_id)
        buyer.inventory.currency[currency] = buyer_balance - total
        seller.inventory.currency[currency] = seller.inventory.currency.get(currency, 0) + total
        return [
            TransactionCompletedEvent(
                buyer_id=buyer.id,
                seller_id=seller.id,
                item_id=item_id,
                quantity=quantity,
                currency=currency,
                unit_price=unit_price,
                total=total,
                buyer_item_ids_after=list(buyer.inventory.item_ids),
                seller_item_ids_after=list(seller.inventory.item_ids),
                buyer_balance_after=buyer.inventory.currency[currency],
                seller_balance_after=seller.inventory.currency[currency],
            )
        ]

    def _buy(self, command: BuyItemCommand) -> list[EventBase]:
        self._require_out_of_encounter(command.actor_id)
        actor = self._entity(command.actor_id)
        merchant, profile = self._merchant_profile(command.merchant_id)
        self._require_colocated(actor, merchant)
        return self._transaction(
            buyer=actor,
            seller=merchant,
            profile=profile,
            item_id=command.item_id,
            quantity=command.quantity,
            merchant_sells=True,
        )

    def _sell(self, command: SellItemCommand) -> list[EventBase]:
        self._require_out_of_encounter(command.actor_id)
        actor = self._entity(command.actor_id)
        merchant, profile = self._merchant_profile(command.merchant_id)
        self._require_colocated(actor, merchant)
        return self._transaction(
            buyer=merchant,
            seller=actor,
            profile=profile,
            item_id=command.item_id,
            quantity=command.quantity,
            merchant_sells=False,
        )

    def execute(self, command: Command) -> list[EventBase]:
        if isinstance(command, SpawnNpcCommand):
            return self._spawn_npc(command)
        if isinstance(command, ExploreLocationCommand):
            return self._explore(command)
        if isinstance(command, SearchLocationCommand):
            return self._search(command)
        if isinstance(command, TravelCommand):
            return self._travel(command)
        if isinstance(command, LootContainerCommand):
            return self._loot(command)
        if isinstance(command, EquipItemCommand):
            return self._equip(command)
        if isinstance(command, UnequipItemCommand):
            return self._unequip(command)
        if isinstance(command, StartDialogueCommand):
            return self._start_dialogue(command)
        if isinstance(command, ChooseDialogueOptionCommand):
            return self._choose_dialogue(command)
        if isinstance(command, StartQuestCommand):
            self._require_out_of_encounter(command.actor_id)
            return self._start_quest(command.actor_id, command.quest_id, allow_existing=False)
        if isinstance(command, AdvanceQuestCommand):
            self._require_out_of_encounter(command.actor_id)
            return self._advance_quest(command.actor_id, command.quest_id, command.trigger)
        if isinstance(command, BuyItemCommand):
            return self._buy(command)
        if isinstance(command, SellItemCommand):
            return self._sell(command)
        raise AdventureError(f"unsupported adventure command: {type(command).__name__}")
