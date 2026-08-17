"""Dependency-free browser reference client served by the FastAPI adapter."""

from __future__ import annotations

INDEX_HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>RPG Engine v0.5 Reference Client</title>
  <style>
    :root { color-scheme: dark; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    body { margin: 0; background: #101216; color: #e7ebf0; }
    header { padding: 1rem 1.25rem; border-bottom: 1px solid #30343c; }
    main { display: grid; grid-template-columns: minmax(18rem, 1fr) minmax(22rem, 1.4fr);
      gap: 1rem; padding: 1rem; }
    section { border: 1px solid #30343c; border-radius: .6rem; padding: 1rem; background: #171a20; }
    label { display: block; margin: .5rem 0 .2rem; color: #aeb8c6; }
    input, textarea, button { box-sizing: border-box; width: 100%; padding: .6rem;
      background: #0f1115; color: #e7ebf0; border: 1px solid #3a414d;
      border-radius: .35rem; }
    textarea { min-height: 10rem; resize: vertical; }
    button { cursor: pointer; margin-top: .6rem; background: #242b35; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; min-height: 10rem; }
    .status { color: #8bd3a8; }
    @media (max-width: 800px) { main { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
<header>
  <strong>RPG Engine v0.5</strong> · browser reference client · REST/OpenAPI + resumable WebSocket
</header>
<main>
  <section>
    <h2>Connection</h2>
    <label for="campaign">Campaign ID</label>
    <input id="campaign" value="demo">
    <label for="actor">Actor ID (optional)</label>
    <input id="actor" placeholder="fighter-1">
    <button id="connect">Connect / refresh</button>
    <p id="status" class="status">Disconnected</p>
    <h2>Observation</h2>
    <pre id="observation"></pre>
  </section>
  <section>
    <h2>Command</h2>
    <textarea id="command">{
  "type": "explore_location",
  "actor_id": "fighter-1"
}</textarea>
    <button id="send">Send authoritative command</button>
    <h2>Events</h2>
    <pre id="events"></pre>
  </section>
</main>
<script>
(() => {
  const campaign = document.querySelector('#campaign');
  const actor = document.querySelector('#actor');
  const status = document.querySelector('#status');
  const observation = document.querySelector('#observation');
  const events = document.querySelector('#events');
  const command = document.querySelector('#command');
  let cursor = 0;
  let socket = null;

  const api = (path) => `/api/v1${path}`;
  const wsUrl = (path) =>
    `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${api(path)}`;

  async function refreshObservation() {
    const query = actor.value.trim() ? `?actor_id=${encodeURIComponent(actor.value.trim())}` : '';
    const id = encodeURIComponent(campaign.value.trim());
    const response = await fetch(api(`/campaigns/${id}/observation${query}`));
    if (!response.ok) throw new Error(await response.text());
    const payload = await response.json();
    cursor = Math.max(cursor, payload.observation.sequence || 0);
    observation.textContent = JSON.stringify(payload.observation, null, 2);
  }

  function appendEvents(payload) {
    if (payload.heartbeat) return;
    for (const event of payload.events || []) {
      if ((event.sequence || 0) <= cursor) continue;
      events.textContent += `${JSON.stringify(event)}\n`;
      cursor = Math.max(cursor, event.sequence || 0);
    }
    events.scrollTop = events.scrollHeight;
    refreshObservation().catch((error) => { status.textContent = error.message; });
  }

  async function connect() {
    if (socket) socket.close();
    await refreshObservation();
    const id = encodeURIComponent(campaign.value.trim());
    socket = new WebSocket(wsUrl(`/campaigns/${id}/events/ws?after=${cursor}`));
    socket.onopen = () => { status.textContent = `Connected; resume cursor ${cursor}`; };
    socket.onmessage = (message) => appendEvents(JSON.parse(message.data));
    socket.onerror = () => { status.textContent = 'WebSocket error'; };
    socket.onclose = () => { status.textContent = `Disconnected at cursor ${cursor}`; };
  }

  async function sendCommand() {
    const id = encodeURIComponent(campaign.value.trim());
    const payload = JSON.parse(command.value);
    const response = await fetch(api(`/campaigns/${id}/commands`), {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(await response.text());
    appendEvents(await response.json());
  }

  document.querySelector('#connect').addEventListener('click', () =>
    connect().catch((error) => { status.textContent = error.message; }));
  document.querySelector('#send').addEventListener('click', () =>
    sendCommand().catch((error) => { status.textContent = error.message; }));
})();
</script>
</body>
</html>'''
