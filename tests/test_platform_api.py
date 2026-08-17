import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from rpg_engine.api.platform import create_platform_app
from rpg_engine.platform import (
    ClientRelease,
    ContentRelease,
    PlatformRegistry,
    PlatformRegistryStore,
    ReleaseArtifact,
)


def test_public_platform_api_and_download_redirects(tmp_path: Path) -> None:
    registry = PlatformRegistry(PlatformRegistryStore(tmp_path / "registry.db"))

    async def seed() -> None:
        await registry.initialize()
        await registry.publish_client(
            ClientRelease(
                client_id="terminal",
                name="Terminal",
                version="1.0.0",
                artifacts=[
                    ReleaseArtifact(
                        platform="linux",
                        arch="x86_64",
                        url="https://example.invalid/terminal.tar.gz",
                        sha256="c" * 64,
                    )
                ],
            )
        )
        await registry.publish_content(
            ContentRelease(
                pack_id="community-pack",
                name="Community Pack",
                version="1.0.0",
                download_url="https://example.invalid/community.zip",
                sha256="d" * 64,
            )
        )

    asyncio.run(seed())
    app = create_platform_app(registry=registry)

    with TestClient(app) as client:
        info = client.get("/v1/platform")
        assert info.status_code == 200
        assert info.json()["engine_version"] == "1.0.0"

        contracts = client.get("/v1/contracts")
        assert contracts.json()["engine_api"] == "1.0"

        download = client.get(
            "/v1/clients/terminal/download",
            params={"platform": "linux", "arch": "x86_64"},
            follow_redirects=False,
        )
        assert download.status_code == 307
        assert download.headers["location"].endswith("terminal.tar.gz")

        marketplace = client.get("/v1/marketplace")
        assert marketplace.json() == {"enabled": False, "listings": []}
