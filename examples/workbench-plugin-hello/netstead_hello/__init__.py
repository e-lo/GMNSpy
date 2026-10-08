"""A minimal netstead Workbench plugin, to copy from (see the "Write a Workbench plugin" cookbook page)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter
from netstead.workbench.plugins import HOST_API, ActionSpec, BaseAction, Host, WorkbenchPlugin
from pydantic import BaseModel, ConfigDict


class Greet(BaseAction):
    """Greet someone (recorded in history like any Action; replays as ``app.do(Greet(name=...))``)."""

    type: Literal["hello.greet"] = "hello.greet"
    name: str


class HelloSettings(BaseModel):
    """``[plugins.hello]`` in netstead.toml."""

    model_config = ConfigDict(extra="forbid")
    prefix: str = "Hello"


def plugin() -> WorkbenchPlugin:
    """The entry point: a fresh plugin whose state lives in this closure (one per session)."""
    greeted = {"count": 0}

    def greet(host: Host, action: Greet) -> str:
        greeted["count"] += 1
        host.publish("greeted", {"name": action.name})
        return f"{host.settings.prefix}, {action.name}!"

    def router(host: Host) -> APIRouter:
        api = APIRouter()

        @api.get("/count")
        def count() -> dict[str, Any]:
            return {"greeted": greeted["count"]}

        return api

    return WorkbenchPlugin(
        id="hello",
        name="Hello",
        version="0.1.0",
        requires_api=HOST_API,
        actions=(ActionSpec(Greet, greet),),
        router=router,
        static_dir=Path(__file__).parent / "static",
        settings_model=HelloSettings,
        state=lambda host: {"greeted": greeted["count"]},
    )
