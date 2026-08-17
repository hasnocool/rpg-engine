# RPG Platform v1

v1.0 turns the deterministic engine into a supported platform boundary.

## Compatibility policy

| Contract | Version |
| --- | --- |
| Engine Python API | 1.0 |
| REST/WebSocket API | 1 |
| Content API | 1.0 |
| Rules plugin API | 1 |

A 1.x release may add optional fields, commands, events, endpoints, or content categories. It must
not reinterpret an existing field or remove a published contract without a deprecation path.
Breaking contract changes require engine 2.0.

## Public Python facade

Applications should prefer `rpg_engine.public.EngineSession` over direct mutation of engine
internals. The facade creates deterministic sessions, executes typed commands, returns immutable
events, exposes deep-copied state, and can reconstruct a session from events.

`public_contract_schemas()` publishes schemas for tooling and code generation.

## Hosted campaigns

`rpg_engine.api.v1.create_hosted_app()` wraps the authenticated multiplayer service as the stable
v1 hosted surface. It retains player accounts/sessions, campaign roles and actor-control scopes,
parties/spectators, optimistic command IDs and idempotent receipts, resumable events, rate limits,
and campaign placement/redirects.

The deterministic `SimulationEngine` remains the only gameplay authority.

## Client releases

`ClientRelease` is a manifest, not executable code. Each artifact records target platform and
architecture, artifact kind/content type, download URL, SHA-256 integrity hash, and optional size.
Resolution selects the highest compatible release for the running engine and requested channel,
platform, and architecture.

The public API returns HTTP redirects to registered artifact URLs. It never executes a downloaded
artifact.

## Community content

`ContentRelease` registers pack ID/name/version, engine constraint, ruleset, download URL/SHA-256,
license, tags, and content dependencies. This complements Creator Platform `manifest.yaml` and
`mod.yaml`; the authoritative content loader still validates a pack before campaign use.

## Optional marketplace

Marketplace listings are discovery metadata layered over already-published content releases.
Marketplace HTTP exposure is disabled unless explicitly enabled. A listing can contain an optional
external checkout URL. v1 contains no payment processor, wallet, stored card data, or entitlement
system.

## Operating surfaces

```text
Local campaign API        rpg_engine.api.v1:create_local_app
Hosted campaign API       rpg_engine.api.v1:create_hosted_app
Distribution API          rpg_engine.api.platform:create_platform_app
Creator API               rpg_engine.creator.app:create_creator_app
```

Production deployments should put authentication/TLS/routing in front of write-capable services
and restrict Creator Platform filesystem access to trusted authors.

## Release registry administration

Publishing is intentionally an administrative/local action:

```bash
rpg-engine platform publish-client client.yaml
rpg-engine platform publish-content pack.yaml
rpg-engine platform publish-listing listing.yaml
```

The public distribution HTTP API is read-only.
