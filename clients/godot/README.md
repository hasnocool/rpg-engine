# Godot 4.7 reference adapter

This directory contains the v0.6 renderer-only Godot adapter.

Copy `addons/rpg_engine` into your Godot 4.7 project, enable **RPG Engine Visual Adapter**, and use
`RPGApiClient` with either `RPGVisualBridge2D` or `RPGVisualBridge3D`.

The adapter consumes `/api/v1/.../visual` snapshots and the resumable `/presentation/ws` stream. It
never owns authoritative RPG state. See `docs/VISUAL_ADAPTERS.md` in the main repository.
