"""Extensible action registry: register new kinds from your own modules."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T", bound="Action")


class Action(Protocol):
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None: ...


@dataclass
class ActionContext:
    """Shared services available to actions."""

    obs: Any
    http_client: Any
    log: logging.Logger
    # Set by the dispatcher (agent): where the action came from (for UI health markers).
    source_storage_key: str | None = None
    source_control_id: str | None = None
    # Optional callback invoked when an action fails.
    on_action_error: Callable[[str, dict[str, Any], BaseException], None] | None = None
    # Optional callback invoked when an action succeeds.
    on_action_success: Callable[[str, dict[str, Any]], None] | None = None
    """Page navigation when using multi-page config (agent.* actions)."""

    pages: Any | None = None
    """Directory containing the config file (for resolving relative asset paths)."""

    config_dir: Path | None = None
    """Spotify Web API (OAuth in web UI); ``None`` if not wired."""

    spotify: Any | None = None
    """Pushes commands to browser sources (``GET /overlay`` + WebSocket ``/ws/overlay``)."""

    overlay_hub: Any | None = None
    # Twitch: optional multi-account context. If set, twitch.* actions may be run per account.
    twitch_accounts: list[dict[str, Any]] | None = None
    twitch_account: dict[str, Any] | None = None
    """Home Assistant REST client (``ha_client.HaClient``); ``None`` if not wired."""

    ha: Any | None = None


Handler = Callable[[ActionContext, dict[str, Any]], Awaitable[None]]

_registry: dict[str, Handler] = {}


def register_action(kind: str) -> Callable[[type[T]], type[T]]:
    """Decorator to register an action class: must define async def run(self, ctx, params)."""

    def deco(cls: type[T]) -> type[T]:
        inst = cls()

        async def handler(ctx: ActionContext, params: dict[str, Any]) -> None:
            await inst.run(ctx, params)

        _registry[kind] = handler
        logger.debug("Registered action kind %r", kind)
        return cls

    return deco


def register_handler(kind: str, fn: Handler) -> None:
    """Register a plain async function as an action handler."""

    _registry[kind] = fn


def get_handler(kind: str) -> Handler | None:
    return _registry.get(kind)


def registered_action_kinds() -> list[str]:
    """All registered action type strings (builtins + plugins loaded at runtime)."""

    return sorted(_registry.keys())


async def run_actions(
    ctx: ActionContext,
    actions: list[dict[str, Any]],
) -> None:
    prev_twitch_account = ctx.twitch_account
    for item in actions:
        kind = item.get("type")
        if not kind:
            logger.warning("Skipping action without type: %s", item)
            continue
        handler = _registry.get(str(kind))
        if handler is None:
            logger.error("Unknown action type %r", kind)
            continue
        params = {k: v for k, v in item.items() if k != "type"}
        logger.debug("Action %r params=%s", kind, params)
        try:
            k = str(kind)
            if k.startswith("twitch.") and ctx.twitch_accounts:
                # Run once per configured Twitch account.
                for acct in ctx.twitch_accounts:
                    if not isinstance(acct, dict):
                        continue
                    ctx.twitch_account = acct
                    await handler(ctx, params)
                    if ctx.on_action_success is not None:
                        try:
                            ctx.on_action_success(k, params)
                        except Exception:
                            logger.debug("on_action_success callback failed", exc_info=True)
            else:
                await handler(ctx, params)
                if ctx.on_action_success is not None:
                    try:
                        ctx.on_action_success(k, params)
                    except Exception:
                        logger.debug("on_action_success callback failed", exc_info=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if ctx.on_action_error is not None:
                try:
                    ctx.on_action_error(str(kind), params, e)
                except Exception:
                    logger.debug("on_action_error callback failed", exc_info=True)
            logger.exception("Action %r failed", kind)
        finally:
            ctx.twitch_account = prev_twitch_account
