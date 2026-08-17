"""AsyncSSH terminal transport exposing the RPG protocol without a host shell."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import asyncssh

from rpg_engine.clients.local import LocalCampaignClient
from rpg_engine.content.loader import load_content_pack_async
from rpg_engine.persistence.sqlite import SQLiteEventStore
from rpg_engine.service import CampaignService
from rpg_engine.terminal import TerminalSession


@dataclass(frozen=True, slots=True)
class SSHServerConfig:
    host: str = "127.0.0.1"
    port: int = 8022
    host_key: Path = Path("ssh_host_key")
    authorized_keys: Path = Path("authorized_keys")
    database_path: Path = Path("rpg_engine.db")
    content_path: Path | None = Path("content/core")
    campaign_id: str | None = None
    actor_from_username: bool = False


class RPGSSHServer:
    """Own an async campaign service and expose it through authenticated SSH sessions."""

    def __init__(self, service: CampaignService, config: SSHServerConfig) -> None:
        self.service = service
        self.config = config

    async def _campaign_for_process(self, process: asyncssh.SSHServerProcess[str]) -> str:
        if self.config.campaign_id is not None:
            return self.config.campaign_id
        if process.command:
            raise ValueError(
                "one-shot SSH commands require --campaign on the server; interactive sessions "
                "may select a campaign after login"
            )
        process.stdout.write("Campaign ID: ")
        campaign_id = (await process.stdin.readline()).strip()
        if not campaign_id:
            raise ValueError("campaign ID is required")
        return campaign_id

    async def handle_process(self, process: asyncssh.SSHServerProcess[str]) -> None:
        try:
            campaign_id = await self._campaign_for_process(process)
            await self.service.state(campaign_id)
            username = str(process.get_extra_info("username") or "")
            actor_id = username if self.config.actor_from_username and username else None
            client = LocalCampaignClient(self.service, campaign_id)
            session = TerminalSession(client, actor_id=actor_id)

            if process.command:
                reply = await session.handle(process.command)
                if reply.text:
                    process.stdout.write(reply.text + "\n")
                process.exit(0)
                return

            process.stdout.write(await session.banner())
            process.stdout.write("\nrpg> ")
            try:
                async for line in process.stdin:
                    reply = await session.handle(line)
                    if reply.text:
                        process.stdout.write(reply.text + "\n")
                    if reply.close:
                        break
                    process.stdout.write("rpg> ")
            except asyncssh.BreakReceived:
                pass
            finally:
                await client.close()
            process.exit(0)
        except (KeyError, ValueError) as exc:
            process.stderr.write(f"ERROR: {exc}\n")
            process.exit(1)


async def create_ssh_listener(
    service: CampaignService, config: SSHServerConfig
) -> asyncssh.SSHAcceptor:
    """Start an authenticated SSH listener using an existing campaign authority service."""

    server = RPGSSHServer(service, config)
    return await asyncssh.listen(
        config.host,
        config.port,
        server_host_keys=[str(config.host_key)],
        authorized_client_keys=str(config.authorized_keys),
        process_factory=server.handle_process,
    )


async def create_ssh_server(config: SSHServerConfig) -> asyncssh.SSHAcceptor:
    """Initialize persistence/content and start a standalone authenticated SSH listener."""

    store = SQLiteEventStore(config.database_path)
    await store.initialize()
    content = None
    if config.content_path is not None:
        content = await load_content_pack_async(config.content_path)
    service = CampaignService(store, content=content)
    return await create_ssh_listener(service, config)
