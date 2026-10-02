"""HTTP + WebSocket adapter around PresenceEngine."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import HEARTBEAT_INTERVAL_S, SESSION_TTL_S, TICK_INTERVAL_S
from app.graph import CONTACT_EDGES, SEED_USERS
from app.models import PresenceEvent
from app.presence import PresenceEngine

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

engine = PresenceEngine()
app = FastAPI(title="RebuildX Presence", version="1.0.0")
app.mount("/static", StaticFiles(directory=WEB), name="static")

# user_id -> live sockets
sockets: dict[str, set[WebSocket]] = {}
ws_session: dict[int, str] = {}  # id(ws) -> session_id


def _contact_count() -> int:
    return len(CONTACT_EDGES) * 2


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/api/users")
async def users() -> dict[str, Any]:
    return {
        "users": [
            {
                "id": uid,
                "name": meta["name"],
                "avatar": meta["avatar"],
                "online": engine.is_online(uid),
            }
            for uid, meta in SEED_USERS.items()
        ]
    }


@app.get("/api/metrics")
async def metrics() -> dict[str, Any]:
    snap = engine.metrics.snapshot(
        online_users=len({s.user_id for s in engine.sessions.values() if s.grace_until is None}),
        sessions=len([s for s in engine.sessions.values() if s.grace_until is None]),
        contacts=_contact_count(),
    )
    snap["sessions_detail"] = engine.sessions_snapshot()
    snap["history"] = engine.metrics.history[-30:]
    snap["heartbeat_interval_s"] = HEARTBEAT_INTERVAL_S
    snap["session_ttl_s"] = SESSION_TTL_S
    return snap


@app.websocket("/ws")
async def presence_socket(ws: WebSocket) -> None:
    await ws.accept()
    user_id: str | None = None
    session_id: str | None = None
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=10)
        hello = json.loads(raw)
        if hello.get("type") != "hello" or hello.get("user_id") not in SEED_USERS:
            await ws.send_json({"type": "error", "error": "send hello with a seeded user_id"})
            await ws.close()
            return
        user_id = hello["user_id"]
        device = hello.get("device", "web")
        session = engine.connect(user_id, device=device)
        session_id = session.session_id
        engine.subscribe(user_id)
        sockets.setdefault(user_id, set()).add(ws)
        ws_session[id(ws)] = session_id

        await _broadcast_events(engine.drain_events())
        await ws.send_json(
            {
                "type": "hello",
                "session_id": session_id,
                "user_id": user_id,
                "name": engine.users[user_id].name,
                "heartbeat_interval_s": HEARTBEAT_INTERVAL_S,
                "session_ttl_s": SESSION_TTL_S,
                "privacy": {
                    "last_seen": engine.users[user_id].privacy.last_seen.value,
                    "online": engine.users[user_id].privacy.online.value,
                },
                "roster": [_view_payload(v) for v in engine.roster_for(user_id)],
            }
        )
        await _push_metrics()

        while True:
            message = json.loads(await ws.receive_text())
            kind = message.get("type")
            if kind == "heartbeat":
                try:
                    engine.heartbeat(session_id)
                except KeyError:
                    await ws.send_json({"type": "error", "error": "session_expired"})
                    continue
                await ws.send_json(
                    {
                        "type": "heartbeat_ack",
                        "seq": message.get("seq"),
                        "server_time": engine.now(),
                    }
                )
            elif kind == "privacy":
                engine.set_privacy(
                    user_id,
                    message.get("last_seen", "contacts"),
                    message.get("online", "contacts"),
                )
                await _broadcast_events(engine.drain_events())
                for viewer_id, conns in list(sockets.items()):
                    roster = [_view_payload(v) for v in engine.roster_for(viewer_id)]
                    for conn in list(conns):
                        await _safe_send(conn, {"type": "roster", "roster": roster})
            elif kind == "kill":
                # Sudden death: stop heartbeats and expire immediately on next tick.
                engine.kill_session(session_id)
            elif kind == "pause_heartbeats":
                pass
            await _push_metrics()
    except (WebSocketDisconnect, asyncio.TimeoutError, json.JSONDecodeError):
        pass
    finally:
        if session_id:
            engine.begin_disconnect(session_id)
        if user_id and ws in sockets.get(user_id, set()):
            sockets[user_id].discard(ws)
        ws_session.pop(id(ws), None)


def _view_payload(view) -> dict[str, Any]:
    record = engine.users[view.user_id]
    return {
        "user_id": view.user_id,
        "name": view.name,
        "avatar": record.avatar,
        "online": view.online,
        "last_seen": view.last_seen,
        "hidden_last_seen": view.hidden_last_seen,
        "hidden_online": view.hidden_online,
        "devices": view.devices,
    }


async def _safe_send(ws: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await ws.send_json(payload)
    except Exception:
        pass


async def _broadcast_events(events: list[PresenceEvent]) -> None:
    for event in events:
        for recipient in event.recipients:
            view = engine.visible_presence(recipient, event.user_id)
            payload = {
                "type": "presence",
                "reason": event.reason.value,
                "at": event.at,
                "presence": _view_payload(view),
            }
            for conn in list(sockets.get(recipient, ())):
                await _safe_send(conn, payload)


async def _push_metrics() -> None:
    snap = engine.metrics.snapshot(
        online_users=len({s.user_id for s in engine.sessions.values() if s.grace_until is None}),
        sessions=len([s for s in engine.sessions.values() if s.grace_until is None]),
        contacts=_contact_count(),
    )
    snap["sessions_detail"] = engine.sessions_snapshot()
    snap["history"] = engine.metrics.history[-20:]
    payload = {"type": "metrics", **snap}
    for conns in sockets.values():
        for conn in list(conns):
            await _safe_send(conn, payload)


async def ticker() -> None:
    while True:
        await asyncio.sleep(TICK_INTERVAL_S)
        events = engine.tick()
        if events:
            await _broadcast_events(events)
            await _push_metrics()


@app.on_event("startup")
async def startup() -> None:
    asyncio.create_task(ticker())
