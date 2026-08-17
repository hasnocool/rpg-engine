"""Client adapters for local and remote RPG engine frontends."""

from rpg_engine.clients.base import CampaignClient
from rpg_engine.clients.http import HttpCampaignClient
from rpg_engine.clients.local import LocalCampaignClient

__all__ = ["CampaignClient", "HttpCampaignClient", "LocalCampaignClient"]
