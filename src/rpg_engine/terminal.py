"""Shared interactive terminal protocol used by local CLI, TUI, and SSH."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass

from rpg_engine import __version__
from rpg_engine.clients.base import CampaignClient
from rpg_engine.commands import Command, parse_command
from rpg_engine.events import Event
from rpg_engine.observations import CampaignObservation
from rpg_engine.terminal_visual import render_visual_snapshot

_HELP = """Commands:
  help                         show this help
  observe [actor_id]           renderer-neutral campaign view
  map [actor_id]               ASCII visual snapshot (also works over SSH)
  visual [actor_id]            alias for map
  state                        raw authoritative state summary
  events [after_sequence]      events after a sequence cursor
  json { ... }                 execute any command payload
  explore <actor_id>
  search <actor_id> [ability]
  travel <actor_id> <destination_id>
  talk <actor_id> <npc_id>
  choose <actor_id> <session_id> <option_id>
  buy <actor_id> <merchant_id> <item_id> [quantity]
  sell <actor_id> <merchant_id> <item_id> [quantity]
  equip <actor_id> <item_id>
  unequip <actor_id> <item_id>
  end-turn <actor_id> [encounter_id]
  quit                         close the terminal session

Any engine command remains available through `json`, so this terminal protocol never needs to
reimplement game rules.
"""


@dataclass(slots=True)
class TerminalReply:
    text: str
    close: bool = False


def _format_event(event: Event) -> str:
    payload = event.model_dump(mode="json")
    event_type = str(payload.pop("type", "event"))
    sequence = payload.pop("sequence", "?")
    payload.pop("campaign_id", None)
    payload.pop("rng_counters_after", None)
    details = ", ".join(f"{key}={value}" for key, value in payload.items())
    return f"#{sequence} {event_type}" + (f" | {details}" if details else "")


def render_events(events: list[Event]) -> str:
    if not events:
        return "No new events."
    return "\n".join(_format_event(event) for event in events)


def render_observation(observation: CampaignObservation) -> str:
    lines = [
        f"Campaign {observation.campaign_id} @ sequence {observation.sequence}",
        f"World time: {observation.time_minutes} minutes",
    ]
    if observation.viewer_id:
        lines.append(f"Viewer: {observation.viewer_id}")
    if observation.location is not None:
        location = observation.location
        lines.append(f"Location: {location.name} [{location.id}]")
        if location.description:
            lines.append(location.description)
        if location.exits:
            exits = ", ".join(
                f"{item.destination_name} ({item.travel_minutes}m)" for item in location.exits
            )
            lines.append(f"Exits: {exits}")
    if observation.actors:
        lines.append("Actors:")
        for actor in observation.actors:
            health = ""
            if actor.health is not None:
                health = f" {actor.health.current}/{actor.health.maximum} HP"
            lines.append(f"  - {actor.name} [{actor.id}]{health}")
    if observation.encounters:
        lines.append("Encounters:")
        for encounter in observation.encounters:
            lines.append(
                f"  - {encounter.id}: round {encounter.round}, active={encounter.active_actor_id}"
            )
    if observation.quests:
        lines.append("Quests:")
        for quest in observation.quests:
            suffix = " complete" if quest.completed else ""
            lines.append(f"  - {quest.name}: {quest.state}{suffix}")
    if observation.dialogues:
        lines.append("Dialogues:")
        for dialogue in observation.dialogues:
            lines.append(
                f"  - {dialogue.session_id}: node={dialogue.node_id}, active={dialogue.active}"
            )
    return "\n".join(lines)


def _shortcut_payload(parts: list[str]) -> object:
    command = parts[0]
    args = parts[1:]
    if command == "explore" and len(args) == 1:
        return {"type": "explore_location", "actor_id": args[0]}
    if command == "search" and len(args) in {1, 2}:
        return {
            "type": "search_location",
            "actor_id": args[0],
            "ability": args[1] if len(args) == 2 else "wisdom",
        }
    if command == "travel" and len(args) == 2:
        return {"type": "travel", "actor_id": args[0], "destination_id": args[1]}
    if command == "talk" and len(args) == 2:
        return {"type": "start_dialogue", "actor_id": args[0], "npc_id": args[1]}
    if command == "choose" and len(args) == 3:
        return {
            "type": "choose_dialogue_option",
            "actor_id": args[0],
            "session_id": args[1],
            "option_id": args[2],
        }
    if command in {"buy", "sell"} and len(args) in {3, 4}:
        return {
            "type": f"{command}_item",
            "actor_id": args[0],
            "merchant_id": args[1],
            "item_id": args[2],
            "quantity": int(args[3]) if len(args) == 4 else 1,
        }
    if command in {"equip", "unequip"} and len(args) == 2:
        return {
            "type": f"{command}_item",
            "actor_id": args[0],
            "item_id": args[1],
        }
    if command == "end-turn" and len(args) in {1, 2}:
        return {
            "type": "end_turn",
            "actor_id": args[0],
            "encounter_id": args[1] if len(args) == 2 else None,
        }
    raise ValueError("invalid shortcut syntax; use `help` or send a `json` command")


def parse_terminal_command(line: str) -> Command:
    stripped = line.strip()
    if not stripped:
        raise ValueError("empty command")
    if stripped.startswith("{"):
        return parse_command(json.loads(stripped))
    if stripped.startswith("json "):
        return parse_command(json.loads(stripped[5:].strip()))
    return parse_command(_shortcut_payload(shlex.split(stripped)))


class TerminalSession:
    """Small stateful shell which delegates all authoritative work to a CampaignClient."""

    def __init__(self, client: CampaignClient, *, actor_id: str | None = None) -> None:
        self.client = client
        self.actor_id = actor_id
        self.event_cursor = 0

    async def banner(self) -> str:
        observation = await self.client.observation(actor_id=self.actor_id)
        self.event_cursor = observation.sequence
        return (
            f"RPG Engine terminal v{__version__}\n\n"
            + render_observation(observation)
            + "\n\n"
            + _HELP
        )

    async def handle(self, line: str) -> TerminalReply:
        stripped = line.strip()
        if not stripped:
            return TerminalReply("")
        parts = shlex.split(stripped)
        control = parts[0].lower() if parts else ""
        if control in {"quit", "exit"}:
            return TerminalReply("Goodbye.", close=True)
        if control in {"help", "?"}:
            return TerminalReply(_HELP)
        if control == "observe":
            actor_id = parts[1] if len(parts) > 1 else self.actor_id
            observation = await self.client.observation(actor_id=actor_id)
            self.event_cursor = max(self.event_cursor, observation.sequence)
            return TerminalReply(render_observation(observation))
        if control in {"map", "visual"}:
            actor_id = parts[1] if len(parts) > 1 else self.actor_id
            visual = await self.client.visual(actor_id=actor_id)
            self.event_cursor = max(self.event_cursor, visual.sequence)
            return TerminalReply(render_visual_snapshot(visual))
        if control == "state":
            state = await self.client.state()
            return TerminalReply(
                f"campaign={state.campaign_id} sequence={state.sequence} "
                f"entities={len(state.entities)} encounters={len(state.encounters)} "
                f"time_minutes={state.time_minutes}"
            )
        if control == "events":
            after = int(parts[1]) if len(parts) > 1 else self.event_cursor
            events = await self.client.events(after_sequence=after)
            if events:
                self.event_cursor = max(self.event_cursor, events[-1].sequence)
            return TerminalReply(render_events(events))

        command = parse_terminal_command(stripped)
        events = await self.client.execute(command)
        if events:
            self.event_cursor = max(self.event_cursor, events[-1].sequence)
        return TerminalReply(render_events(events))
