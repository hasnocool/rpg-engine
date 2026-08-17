"""Compatibility-aware client/content/community release resolution."""

from __future__ import annotations

from packaging.version import Version

from rpg_engine import __version__
from rpg_engine.platform.models import (
    ClientRelease,
    ContentRelease,
    MarketplaceListing,
    ReleaseArtifact,
    ResolvedClient,
)
from rpg_engine.platform.store import PlatformRegistryStore
from rpg_engine.versioning import version_satisfies


class DistributionError(ValueError):
    pass


class PlatformRegistry:
    def __init__(
        self,
        store: PlatformRegistryStore,
        *,
        engine_version: str = __version__,
    ) -> None:
        self.store = store
        self.engine_version = engine_version

    async def initialize(self) -> None:
        await self.store.initialize()

    async def publish_client(self, release: ClientRelease) -> None:
        if not version_satisfies(self.engine_version, release.engine):
            raise DistributionError(
                f"client {release.client_id} {release.version} is incompatible with "
                f"engine {self.engine_version}"
            )
        await self.store.put_client(release)

    async def publish_content(self, release: ContentRelease) -> None:
        if not version_satisfies(self.engine_version, release.engine):
            raise DistributionError(
                f"content {release.pack_id} {release.version} is incompatible with "
                f"engine {self.engine_version}"
            )
        await self.store.put_content(release)

    async def publish_listing(self, listing: MarketplaceListing) -> None:
        releases = await self.store.content(pack_id=listing.pack_id)
        if not any(item.version == listing.version for item in releases):
            raise DistributionError(
                f"listing references unpublished content {listing.pack_id} {listing.version}"
            )
        await self.store.put_listing(listing)

    async def resolve_client(
        self,
        client_id: str,
        *,
        platform: str,
        arch: str = "any",
        channel: str = "stable",
    ) -> ResolvedClient:
        candidates: list[tuple[Version, int, ClientRelease, ReleaseArtifact]] = []
        for release in await self.store.clients(client_id=client_id, channel=channel):
            if not version_satisfies(self.engine_version, release.engine):
                continue
            for artifact in release.artifacts:
                platform_match = artifact.platform in {platform, "any"}
                arch_match = artifact.arch in {arch, "any"}
                if platform_match and arch_match:
                    specificity = int(artifact.platform == platform) + int(artifact.arch == arch)
                    candidates.append((Version(release.version), specificity, release, artifact))
        if not candidates:
            raise DistributionError(
                f"no compatible {channel} client release for {client_id} on {platform}/{arch}"
            )
        _, _, release, artifact = max(candidates, key=lambda item: (item[0], item[1]))
        return ResolvedClient(release=release, artifact=artifact)

    async def resolve_content(self, pack_id: str) -> ContentRelease:
        candidates = [
            release
            for release in await self.store.content(pack_id=pack_id)
            if version_satisfies(self.engine_version, release.engine)
        ]
        if not candidates:
            raise DistributionError(f"no compatible content release for {pack_id}")
        return max(candidates, key=lambda item: Version(item.version))

    async def clients(self) -> list[ClientRelease]:
        return sorted(
            await self.store.clients(),
            key=lambda item: (item.client_id, Version(item.version)),
        )

    async def content(self) -> list[ContentRelease]:
        return sorted(
            await self.store.content(),
            key=lambda item: (item.pack_id, Version(item.version)),
        )

    async def listings(self) -> list[MarketplaceListing]:
        return sorted(await self.store.listings(), key=lambda item: item.listing_id)
