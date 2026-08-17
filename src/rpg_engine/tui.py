"""Textual TUI adapter for the remote v1 API."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Input, RichLog, Static

from rpg_engine.clients.http import HttpCampaignClient
from rpg_engine.terminal import TerminalSession, render_events, render_observation


class RPGTUI(App[None]):
    """Thin TUI: presentation only, all authority remains in the engine service."""

    CSS = """
    Screen { layout: vertical; }
    #panes { height: 1fr; }
    #observation { width: 1fr; border: solid $accent; padding: 1; overflow-y: auto; }
    #events { width: 1fr; border: solid $secondary; }
    #command { dock: bottom; }
    """
    BINDINGS = [("ctrl+q", "quit", "Quit"), ("ctrl+r", "refresh", "Refresh")]

    def __init__(self, base_url: str, campaign_id: str, *, actor_id: str | None = None) -> None:
        super().__init__()
        self.client = HttpCampaignClient(base_url, campaign_id)
        self.session = TerminalSession(self.client, actor_id=actor_id)
        self._cursor = 0

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="panes"):
            yield Static("Loading observation...", id="observation")
            yield RichLog(id="events", wrap=True, highlight=True, markup=False)
        yield Input(placeholder="help | observe | json {...}", id="command")
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_view()
        self.set_interval(1.0, self.refresh_view)

    async def on_unmount(self) -> None:
        await self.client.close()

    async def action_refresh(self) -> None:
        await self.refresh_view()

    async def refresh_view(self) -> None:
        events = await self.client.events(after_sequence=self._cursor)
        if events:
            self._cursor = events[-1].sequence
            self.session.event_cursor = self._cursor
            self.query_one("#events", RichLog).write(render_events(events))
        observation = await self.client.observation(actor_id=self.session.actor_id)
        self._cursor = max(self._cursor, observation.sequence)
        self.session.event_cursor = self._cursor
        self.query_one("#observation", Static).update(render_observation(observation))

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        line = event.value.strip()
        event.input.value = ""
        if not line:
            return
        try:
            reply = await self.session.handle(line)
        except Exception as exc:
            self.query_one("#events", RichLog).write(f"ERROR: {exc}")
            return
        if reply.text:
            self.query_one("#events", RichLog).write(reply.text)
        if reply.close:
            self.exit()
            return
        await self.refresh_view()
