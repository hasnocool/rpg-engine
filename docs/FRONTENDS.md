# v0.5 Multiple Frontends

v0.5 makes the deterministic engine practical to use from several presentation layers without
moving authority into those clients.

## Transport architecture

```text
                             ┌───────────────────────┐
                             │   CampaignService     │
                             │ authoritative state   │
                             └───────────┬───────────┘
                                         │
                 ┌───────────────────────┼──────────────────────┐
                 │                       │                      │
           REST/OpenAPI          resumable WebSocket      local adapter
                 │                       │                      │
          ┌──────┴──────┐         browser / remote         SSH server
          │             │             clients                  │
    interactive CLI   Textual TUI                              │
                                                               │
                                                        normal ssh client
```

Every frontend sends the same typed command models. None of the clients may mutate campaign state
or calculate authoritative outcomes.

## Stable v1 HTTP contract

New clients should use `/api/v1`.

Key endpoints:

```text
GET  /api/v1/health
POST /api/v1/campaigns
GET  /api/v1/campaigns/{id}/state
GET  /api/v1/campaigns/{id}/observation
GET  /api/v1/campaigns/{id}/events?after=N
POST /api/v1/campaigns/{id}/commands
WS   /api/v1/campaigns/{id}/events/ws?after=N
GET  /client
```

The original unversioned v0.1-v0.3 REST routes remain available as deprecated compatibility aliases.

## Renderer-neutral observation API

`CampaignObservation` is intentionally smaller and more presentation-oriented than `WorldState`.
It exposes logical concepts such as:

- current location and known exits
- co-located actors
- encounter turn/budget summaries
- quest progress
- active dialogue sessions
- equipment and currency summaries

Hidden world connections are not included until they have been discovered by the requesting actor.
This is not yet a full perception/vision system; that belongs to the later AI/actor milestones.

## Resumable WebSocket subscriptions

Clients connect with an event cursor:

```text
/api/v1/campaigns/demo/events/ws?after=418
```

The server reads events from the persistent event log after sequence 418 before waiting for new
ones. This means a disconnected client can resume without relying on an in-memory broadcast buffer.
Periodic heartbeat envelopes keep quiet connections alive without advancing the event cursor.

The WebSocket can also accept ordinary engine command JSON. Commands are still validated and
executed by the same `CampaignService` used by REST and SSH.

## Interactive CLI

Run the API server:

```bash
rpg-engine serve --host 127.0.0.1 --port 8000
```

Then connect the terminal client:

```bash
rpg-engine play --server http://127.0.0.1:8000 --campaign demo
```

The prompt uses `prompt_toolkit`'s asynchronous input API, so terminal input does not block the
application event loop.

## Textual TUI

```bash
rpg-engine tui --server http://127.0.0.1:8000 --campaign demo
```

The TUI is deliberately thin. It renders the observation API, tails event sequences, and routes
commands through the shared terminal command parser.

## Browser reference client

Start the API and open `/client` in a browser. The reference page uses only browser-native
JavaScript and connects to the versioned REST and resumable WebSocket endpoints.

It is intended as a protocol example, not as the final web game UI.

## SSH terminal transport

v0.5 adds an authenticated SSH endpoint using AsyncSSH. This is an RPG protocol endpoint, **not an
operating-system shell**. It does not run subprocesses or expose SFTP/SCP. SSH `exec` requests, when
a fixed campaign is configured, are interpreted as one RPG terminal command.

Create a server host key and an authorized-keys file using your normal OpenSSH tooling, then run:

```bash
rpg-engine serve-ssh \
  --host 127.0.0.1 \
  --port 8022 \
  --host-key ssh_host_key \
  --authorized-keys authorized_keys \
  --campaign demo
```

Connect with a standard SSH client:

```bash
ssh -p 8022 player@127.0.0.1
```

If `--campaign` is omitted, interactive SSH users are prompted for a campaign ID after login.
`--actor-from-username` can map an authenticated SSH username to the observation actor ID.

## Running API + SSH together

When multiple transports should serve the same campaigns, prefer:

```bash
rpg-engine serve-all \
  --api-host 127.0.0.1 --api-port 8000 \
  --ssh-host 127.0.0.1 --ssh-port 8022 \
  --host-key ssh_host_key \
  --authorized-keys authorized_keys
```

`serve-all` deliberately shares one in-process `CampaignService` between the API and SSH listeners.
This preserves the current single-process authority model and avoids independent cached engine
instances racing against one SQLite campaign.

Multi-process/horizontal campaign authority is deferred to the multiplayer milestone.

## Terminal protocol

Human-friendly shortcuts are presentation sugar only:

```text
help
observe [actor_id]
state
events [after_sequence]
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
json { ... any typed engine command ... }
quit
```

The `json` escape hatch means new engine commands do not require an immediate terminal-parser
release before they can be used.
