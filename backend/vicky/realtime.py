"""Realtime fan-out: one multiplexed WebSocket per browser tab, bridged through Redis pub/sub so the
API, the worker and every replica see the same events.

Envelope (docs/05-BACKEND-SCHEMA.md §7): {type, channel, session_id, version, ts, payload}.
Clients dedupe by version and re-fetch REST state when they reconnect (Postgres is the record).
"""

import asyncio
import contextlib
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from vicky import kv
from vicky.auth import Gate, code_tag, token_ok
from vicky.config import get_settings

log = logging.getLogger(__name__)
router = APIRouter()
PREFIX = "vicky:"


class Hub:
    def __init__(self) -> None:
        self.sockets: dict[str, set[WebSocket]] = defaultdict(set)
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _listen(self) -> None:
        while True:
            try:
                pubsub = kv.client().pubsub()
                await pubsub.psubscribe(f"{PREFIX}session:*", f"{PREFIX}dashboard:*", f"{PREFIX}engagement:*")
                async for msg in pubsub.listen():
                    if msg.get("type") != "pmessage":
                        continue
                    channel = str(msg["channel"])[len(PREFIX):]
                    await self._deliver(channel, msg["data"])
            except asyncio.CancelledError:
                raise
            except Exception as e:  # reconnect after Redis hiccups
                log.warning("pubsub listener error: %s", e)
                await asyncio.sleep(1.0)

    async def _deliver(self, channel: str, data: str) -> None:
        dead = []
        for ws in list(self.sockets.get(channel, ())):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.sockets[channel].discard(ws)

    def add(self, channel: str, ws: WebSocket) -> None:
        self.sockets[channel].add(ws)

    def remove(self, ws: WebSocket) -> None:
        for channel in list(self.sockets):
            self.sockets[channel].discard(ws)
            if not self.sockets[channel]:
                del self.sockets[channel]  # don't keep empty channel entries around forever


hub = Hub()


async def publish(channel: str, type_: str, payload: dict[str, Any] | None = None) -> dict:
    """Publish an event on a channel such as `session:<id>` or `dashboard:<id>`."""
    try:
        version = int(await kv.client().incr(f"{PREFIX}ver:{channel}"))
    except Exception:
        version = int(datetime.now(UTC).timestamp() * 1000)
    env = {"type": type_, "channel": channel, "session_id": channel.split(":", 1)[-1], "version": version,
           "ts": datetime.now(UTC).isoformat(), "payload": payload or {}}
    data = json.dumps(env, default=str)
    try:
        await kv.client().publish(f"{PREFIX}{channel}", data)
    except Exception:
        await hub._deliver(channel, data)
    return env


def _ws_signer() -> TimestampSigner:
    # Salted with the access code's tag: like the cookie, a socket token dies with the code it was issued under.
    return TimestampSigner(get_settings().cookie_secret, salt=f"vicky-ws.{code_tag().decode()}")


@router.get("/realtime/token", dependencies=[Gate])
async def realtime_token(request: Request) -> dict:
    return {"token": _ws_signer().sign(b"ws").decode()}


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    token = ws.query_params.get("token")
    cookie_ok = token_ok(ws.cookies.get(get_settings().cookie_name))
    token_valid = False
    if token:
        try:
            _ws_signer().unsign(token, max_age=3600)
            token_valid = True
        except (BadSignature, SignatureExpired):
            token_valid = False
    if not (cookie_ok or token_valid):
        await ws.close(code=4401)
        return
    await ws.accept()
    channels = [c for c in (ws.query_params.get("channels") or ws.query_params.get("session") or "").split(",") if c]
    for c in channels:
        hub.add(c, ws)
    try:
        versions = {}
        for c in channels:
            with contextlib.suppress(Exception):
                versions[c] = int(await kv.client().get(f"{PREFIX}ver:{c}") or 0)
        await ws.send_text(json.dumps({"type": "hello", "channels": channels, "versions": versions}))
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
            except ValueError:
                continue
            if data.get("type") == "subscribe" and isinstance(data.get("channel"), str):
                hub.add(data["channel"], ws)
            elif data.get("type") == "unsubscribe" and isinstance(data.get("channel"), str):
                hub.sockets.get(data["channel"], set()).discard(ws)
            elif data.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(ws)
