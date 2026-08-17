# v0.8 Hosted Multiplayer

v0.8 adds an authenticated hosted-campaign boundary around the deterministic simulation. The
multiplayer layer coordinates people, sessions, retries, spectators, rate limits, and campaign
placement; it does **not** replace `SimulationEngine`, `CampaignService`, or the immutable event log.

## Authority boundary

```text
player / spectator
       |
       | bearer session + client_command_id
       v
+-------------------------------+
| HostedCampaignService         |
| - auth + membership           |
| - role/actor authorization    |
| - idempotency receipts        |
| - database rate limits        |
| - campaign placement          |
| - reconnect/resume cursors    |
+---------------+---------------+
                |
                | validated Command
                v
+-------------------------------+
| CampaignService               |
| per-campaign asyncio.Lock     |
+---------------+---------------+
                |
                v
       SimulationEngine
                |
         immutable Events
                |
          SQLite event log
```

Clients still submit intent. Multiplayer authentication never makes a client-provided damage value,
movement cost, quest result, or AI proposal authoritative.

## Hosted server

The authenticated hosted API is separate from the legacy development API:

```bash
uvicorn rpg_engine.api.hosted:app --host 0.0.0.0 --port 8000
```

For multiple nodes, construct `create_hosted_app()` with a unique `node_id` and a directly routable
`public_url` for each node.

Do not expose the legacy unauthenticated development adapter directly to the public Internet. Use
TLS termination in front of the hosted API.

## Authentication

Player accounts use:

- generated UUID player IDs
- PBKDF2-HMAC-SHA256 password hashes
- 310,000 iterations
- random per-account salts
- opaque random session tokens
- only a SHA-256 hash of the session token is persisted
- expiring sessions

Password hashing and verification run through `asyncio.to_thread()` so the CPU-heavy KDF does not
block the server event loop.

Main endpoints:

```text
POST   /v1/players
POST   /v1/sessions
DELETE /v1/sessions/current
```

REST endpoints use `Authorization: Bearer <token>`.

The WebSocket reference endpoint accepts the session token as a query parameter for browser/client
compatibility. Deploy it only over `wss://`; query parameters may appear in proxy logs unless the
proxy is configured to redact them.

## Campaign membership and parties

Campaign roles are:

- `owner` — full campaign authority
- `player` — may issue actor-bound commands only for assigned actors
- `spectator` — read-only

A player membership stores a set of `controlled_actor_ids`. Unknown actor IDs are rejected when an
owner grants membership. Commands without a safe player actor binding default to owner-only, which
means newly introduced command types are conservative until explicitly classified.

Party membership is separate from campaign role. A campaign member may create a party, its creator
becomes leader, and the leader may add other non-spectator campaign members.

```text
PUT  /v1/campaigns/{campaign_id}/members
POST /v1/campaigns/{campaign_id}/parties
POST /v1/parties/{party_id}/members
```

## Optimistic command IDs and idempotency

Hosted commands are wrapped in a transport envelope:

```json
{
  "client_command_id": "web-7f15c1a1",
  "command": {
    "type": "move_actor",
    "actor_id": "hero",
    "position": {"area": "village"}
  }
}
```

The client may optimistically update its UI while the request is in flight. The authoritative
response echoes `client_command_id` and returns the committed event sequence range.

The receipt key is:

```text
campaign_id + player_id + client_command_id
```

A canonical SHA-256 hash of the typed command prevents one client ID from being reused for a
different command.

Receipt states are:

```text
pending -> committed
        -> failed
```

Committed retries replay the stored response without executing the command again. Failed retries
return the stored failure. A pending receipt has a short execution lease and random execution token.
After a crashed executor's lease expires another request may take over, while fencing prevents the
stale executor from overwriting the takeover receipt.

Clients can explicitly reconcile an optimistic command after reconnect:

```text
GET /v1/campaigns/{campaign_id}/commands/{client_command_id}
```

## Reconnect and resume

The event log remains the source of truth. Clients reconnect with the highest global event sequence
they have processed:

```text
GET /v1/campaigns/{campaign_id}/events?after=418
WS  /v1/campaigns/{campaign_id}/events/ws?after=418&token=...
```

The stream first replays persisted events after the cursor, then waits for new events. In-process
`asyncio.Condition` objects are only wake-up hints; heartbeat timeouts cause the stream to poll the
persisted event log again, so events written by another process are eventually observed too.

A heartbeat envelope does not advance the cursor.

For ordinary players, the **global cursor still advances across hidden events** even when those
events are filtered from the payload. This prevents reconnect loops repeatedly reading the same
hidden sequences.

## Event visibility

Owners and spectators may read the full authoritative event stream. Ordinary players receive:

- events that reference one of their controlled actors
- public calendar/time/weather events

Events that only concern unrelated actors are omitted. This is a conservative transport-level
filter; renderer-specific fog-of-war or richer player observations can layer on the v0.5 observation
contracts later.

Raw `WorldState` is owner/spectator-only in the hosted API.

## Rate limits

Rate limits are persisted in SQLite rather than held only in process memory. This makes limits
consistent across multiple workers using the same coordination database.

Default limits:

- authentication attempts: 20/minute per player ID
- commands: 60/minute per player/campaign
- REST reads: 300/minute per player/campaign

A rejected request returns HTTP 429 plus `Retry-After`.

The store uses fixed one-minute windows. The API surface deliberately keeps the policy small and
predictable; deployments can place additional IP/WAF limits in front of the service.

## Horizontal campaign placement

Every hosted node registers:

```text
node_id
public_url
last_seen_at
expires_at
```

Nodes send non-blocking heartbeats. Campaigns are assigned with deterministic rendezvous hashing
over currently live nodes, then protected by a persisted placement lease and monotonic placement
epoch.

If a placement node expires:

1. the expired node is excluded from the live set;
2. the next request deterministically selects a surviving node;
3. the placement epoch increments;
4. requests reaching another node receive HTTP 307 with the owning node's `public_url`;
5. WebSocket clients receive a redirect envelope and reconnect to the owner.

`MultiplayerStore` is the SQLite reference coordination backend. It supports multiple processes on a
host with WAL/busy-timeout coordination. A multi-host production deployment should provide a shared
coordination database with equivalent transactional semantics rather than placing SQLite on an
unsafe network filesystem.

## Non-blocking behavior

The hosted layer uses:

- `asyncio.Lock` for local receipt serialization
- `asyncio.Condition` for event wakeups
- `asyncio.sleep` for node heartbeats
- `asyncio.to_thread` for PBKDF2 and synchronous SQLite coordination operations

No request handler performs blocking sleeps or direct blocking filesystem/network I/O on the event
loop.

## Replay and determinism

Authentication, rate-limit counters, command receipts, parties, sessions, and placement leases are
**transport/hosting state**, not deterministic game state. They are therefore not added to
`WorldState` or the simulation event reducer.

Once a command passes hosted authorization, the same deterministic `CampaignService` and
`SimulationEngine` used by local play produce the authoritative game events. Multiplayer therefore
changes who may submit commands and how retries are coordinated, not how game reality is resolved.
