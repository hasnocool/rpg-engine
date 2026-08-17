"""Stable v1 wrappers around local and hosted campaign APIs."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from rpg_engine import __version__
from rpg_engine.api.app import create_app as _create_local_app
from rpg_engine.api.hosted import create_hosted_app as _create_hosted_app


def _stabilize(app: FastAPI, title: str) -> FastAPI:
    app.title = title
    app.version = __version__
    return app


def create_local_app(**kwargs: Any) -> FastAPI:
    return _stabilize(_create_local_app(**kwargs), "RPG Engine v1 Local API")


def create_hosted_app(**kwargs: Any) -> FastAPI:
    return _stabilize(_create_hosted_app(**kwargs), "RPG Engine v1 Hosted API")


app = create_local_app()
