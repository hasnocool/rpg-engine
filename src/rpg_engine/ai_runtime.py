"""Authoritative AI Game Master memory and proposal validation runtime."""

from __future__ import annotations

from dataclasses import dataclass

from rpg_engine.commands import (
    ActivateAiProposalCommand,
    Command,
    ForgetNpcMemoryCommand,
    GenerateDynamicQuestCommand,
    RecordNpcMemoryCommand,
    StartEncounterCommand,
    SubmitAiEncounterProposalCommand,
    SubmitAiQuestProposalCommand,
)
from rpg_engine.content.models import ContentRegistry
from rpg_engine.events import (
    AiProposalActivatedEvent,
    AiProposalEvaluatedEvent,
    EventBase,
    NpcMemoryForgottenEvent,
    NpcMemoryRecordedEvent,
)
from rpg_engine.models import AiProposalRecord, NpcMemory, WorldState


class AIGameMasterError(ValueError):
    """Rejected AI-domain command or invalid AI proposal state."""


@dataclass(frozen=True, slots=True)
class AIExecutionResult:
    events: tuple[EventBase, ...]
    follow_up: Command | None = None
    proposal_id: str | None = None


class AIGameMasterRuntime:
    """Stores NPC context and validates AI proposals before standard engine commands run."""

    def __init__(self, world: WorldState, *, content: ContentRegistry) -> None:
        self.world = world
        self.content = content

    @staticmethod
    def handles(command: Command) -> bool:
        return isinstance(
            command,
            RecordNpcMemoryCommand
            | ForgetNpcMemoryCommand
            | SubmitAiEncounterProposalCommand
            | SubmitAiQuestProposalCommand
            | ActivateAiProposalCommand,
        )

    def _entity_exists(self, actor_id: str) -> bool:
        return actor_id in self.world.entities

    def _record_memory(self, command: RecordNpcMemoryCommand) -> AIExecutionResult:
        if not self._entity_exists(command.actor_id):
            raise AIGameMasterError(f"unknown actor: {command.actor_id}")
        memories = self.world.npc_memories.setdefault(command.actor_id, {})
        if command.memory_id in memories:
            raise AIGameMasterError(f"memory already exists: {command.memory_id}")
        now = (
            self.world.calendar.absolute_minute
            if self.world.living_world_initialized
            else self.world.time_minutes
        )
        expires_at = (
            None
            if command.expires_after_minutes is None
            else now + command.expires_after_minutes
        )
        memory = NpcMemory(
            id=command.memory_id,
            actor_id=command.actor_id,
            summary=command.summary,
            importance=command.importance,
            tags=set(command.tags),
            subject_ids=set(command.subject_ids),
            created_sequence=self.world.sequence + 1,
            created_at_minute=now,
            expires_at_minute=expires_at,
        )
        memories[memory.id] = memory
        return AIExecutionResult(
            events=(NpcMemoryRecordedEvent(memory=memory.model_copy(deep=True)),)
        )

    def _forget_memory(self, command: ForgetNpcMemoryCommand) -> AIExecutionResult:
        memories = self.world.npc_memories.get(command.actor_id)
        if memories is None or command.memory_id not in memories:
            raise AIGameMasterError(f"unknown memory: {command.memory_id}")
        memories.pop(command.memory_id)
        return AIExecutionResult(
            events=(
                NpcMemoryForgottenEvent(
                    actor_id=command.actor_id,
                    memory_id=command.memory_id,
                    reason=command.reason,
                ),
            )
        )

    def _active_encounter_for(self, actor_id: str) -> bool:
        return any(
            encounter.active and actor_id in encounter.participant_ids
            for encounter in self.world.encounters.values()
        )

    def _validate_encounter(self, command: SubmitAiEncounterProposalCommand) -> AIExecutionResult:
        proposal = command.proposal
        if proposal.id in self.world.ai_proposals:
            raise AIGameMasterError(f"proposal already exists: {proposal.id}")

        reasons: list[str] = []
        if len(set(proposal.participant_ids)) != len(proposal.participant_ids):
            reasons.append("participants must be unique")
        if len(set(proposal.participant_ids)) < 2:
            reasons.append("encounter requires at least two unique participants")

        entities = []
        for actor_id in proposal.participant_ids:
            entity = self.world.entities.get(actor_id)
            if entity is None:
                reasons.append(f"unknown participant: {actor_id}")
                continue
            entities.append(entity)
            if not entity.is_alive:
                reasons.append(f"participant is defeated: {actor_id}")
            if self._active_encounter_for(actor_id):
                reasons.append(f"participant already in active encounter: {actor_id}")

        resolved_location = proposal.location_id
        if resolved_location is not None and resolved_location not in self.content.locations:
            reasons.append(f"unknown location: {resolved_location}")
        if resolved_location is None and entities:
            resolved_location = entities[0].position.area
        if resolved_location is None:
            reasons.append("proposal requires a logical location")
        elif any(entity.position.area != resolved_location for entity in entities):
            reasons.append("all participants must be at the proposed location")

        encounter_id = f"ai:{proposal.id}"
        if encounter_id in self.world.encounters:
            reasons.append(f"encounter id already exists: {encounter_id}")

        status = "rejected" if reasons else "validated"
        record = AiProposalRecord(
            id=proposal.id,
            kind="encounter",
            status=status,
            reasons=reasons,
            encounter=proposal.model_copy(update={"location_id": resolved_location}, deep=True),
            created_sequence=self.world.sequence + 1,
        )
        self.world.ai_proposals[record.id] = record
        follow_up: Command | None = None
        if command.activate and not reasons:
            follow_up = StartEncounterCommand(
                encounter_id=encounter_id,
                participant_ids=list(proposal.participant_ids),
            )
        return AIExecutionResult(
            events=(AiProposalEvaluatedEvent(record=record.model_copy(deep=True)),),
            follow_up=follow_up,
            proposal_id=record.id,
        )

    def _validate_quest(self, command: SubmitAiQuestProposalCommand) -> AIExecutionResult:
        proposal = command.proposal
        if proposal.id in self.world.ai_proposals:
            raise AIGameMasterError(f"proposal already exists: {proposal.id}")

        reasons: list[str] = []
        if proposal.origin_location_id not in self.content.locations:
            reasons.append(f"unknown origin location: {proposal.origin_location_id}")
        if proposal.template_id not in self.content.dynamic_quest_templates:
            reasons.append(f"unknown dynamic quest template: {proposal.template_id}")
        if proposal.actor_id is not None:
            actor = self.world.entities.get(proposal.actor_id)
            if actor is None:
                reasons.append(f"unknown actor: {proposal.actor_id}")
            elif not actor.is_alive:
                reasons.append(f"actor is defeated: {proposal.actor_id}")

        status = "rejected" if reasons else "validated"
        record = AiProposalRecord(
            id=proposal.id,
            kind="quest",
            status=status,
            reasons=reasons,
            quest=proposal.model_copy(deep=True),
            created_sequence=self.world.sequence + 1,
        )
        self.world.ai_proposals[record.id] = record
        follow_up: Command | None = None
        if command.activate and not reasons:
            follow_up = GenerateDynamicQuestCommand(
                origin_location_id=proposal.origin_location_id,
                template_id=proposal.template_id,
            )
        return AIExecutionResult(
            events=(AiProposalEvaluatedEvent(record=record.model_copy(deep=True)),),
            follow_up=follow_up,
            proposal_id=record.id,
        )

    def _activate(self, command: ActivateAiProposalCommand) -> AIExecutionResult:
        try:
            record = self.world.ai_proposals[command.proposal_id]
        except KeyError as exc:
            raise AIGameMasterError(f"unknown proposal: {command.proposal_id}") from exc
        if record.status != "validated":
            raise AIGameMasterError("only validated proposals can be activated")

        follow_up: Command
        if record.kind == "encounter":
            assert record.encounter is not None
            follow_up = StartEncounterCommand(
                encounter_id=f"ai:{record.id}",
                participant_ids=list(record.encounter.participant_ids),
            )
        else:
            assert record.quest is not None
            follow_up = GenerateDynamicQuestCommand(
                origin_location_id=record.quest.origin_location_id,
                template_id=record.quest.template_id,
            )
        return AIExecutionResult(events=(), follow_up=follow_up, proposal_id=record.id)

    def mark_activated(self, proposal_id: str) -> EventBase:
        record = self.world.ai_proposals[proposal_id]
        if record.status != "validated":
            raise AIGameMasterError("proposal is not in validated state")
        record.status = "activated"
        record.activated_sequence = self.world.sequence + 1
        return AiProposalActivatedEvent(record=record.model_copy(deep=True))

    def execute(self, command: Command) -> AIExecutionResult:
        if isinstance(command, RecordNpcMemoryCommand):
            return self._record_memory(command)
        if isinstance(command, ForgetNpcMemoryCommand):
            return self._forget_memory(command)
        if isinstance(command, SubmitAiEncounterProposalCommand):
            return self._validate_encounter(command)
        if isinstance(command, SubmitAiQuestProposalCommand):
            return self._validate_quest(command)
        if isinstance(command, ActivateAiProposalCommand):
            return self._activate(command)
        raise AIGameMasterError(f"unsupported AI command: {type(command).__name__}")
