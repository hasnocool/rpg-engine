from pathlib import Path

import pytest

from rpg_engine.platform import (
    ClientRelease,
    ContentRelease,
    DistributionError,
    MarketplaceListing,
    PlatformRegistry,
    PlatformRegistryStore,
    ReleaseArtifact,
)


@pytest.mark.asyncio
async def test_registry_resolves_latest_compatible_client_and_content(tmp_path: Path) -> None:
    registry = PlatformRegistry(PlatformRegistryStore(tmp_path / "registry.db"))
    await registry.initialize()

    for version in ("1.0.0", "1.1.0"):
        await registry.publish_client(
            ClientRelease(
                client_id="terminal",
                name="Terminal Client",
                version=version,
                artifacts=[
                    ReleaseArtifact(
                        platform="linux",
                        arch="x86_64",
                        url=f"https://example.invalid/terminal-{version}.tar.gz",
                        sha256="a" * 64,
                    )
                ],
            )
        )

    await registry.publish_content(
        ContentRelease(
            pack_id="demo-world",
            name="Demo World",
            version="1.2.0",
            download_url="https://example.invalid/demo-world.zip",
            sha256="b" * 64,
            license="CC0-1.0",
        )
    )

    client = await registry.resolve_client("terminal", platform="linux", arch="x86_64")
    content = await registry.resolve_content("demo-world")

    assert client.release.version == "1.1.0"
    assert content.version == "1.2.0"


@pytest.mark.asyncio
async def test_marketplace_listing_must_reference_published_content(tmp_path: Path) -> None:
    registry = PlatformRegistry(PlatformRegistryStore(tmp_path / "registry.db"))
    await registry.initialize()
    listing = MarketplaceListing(
        listing_id="demo",
        pack_id="missing",
        version="1.0.0",
        title="Demo",
        publisher="creator",
    )

    with pytest.raises(DistributionError, match="unpublished content"):
        await registry.publish_listing(listing)
