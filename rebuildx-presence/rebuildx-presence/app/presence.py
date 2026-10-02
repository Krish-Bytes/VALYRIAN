"""Presence engine: sessions, heartbeats, TTL, grace, privacy, fanout.

This module has no I/O. The WebSocket layer is a thin adapter so the viva
defense can point at unit tests instead of "it works on my laptop".
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from typing import Callable

from app.config import GRACE_DISCONNECT_S, SESSION_TTL_S
from app.graph import adjacency, seed_records
from app.metrics import Metrics
from app.models import (
    EventReason,
    PresenceEvent,
    PresenceView,
    PrivacySettings,
    Session,
    UserRecord,
    Visibility,
)

Clock = Callable[[], float]


class PresenceEngine:
    def __init__(self, clock: Clock | None = None) -> None:
        self._now: Clock = clock or time.time
        self.users: dict[str, UserRecord] = seed_records()
        self.contacts: dict[str, set[str]] = adjacency()
        self.sessions: dict[str, Session] = {}
        self.sessions_by_user: dict[str, set[str]] = defaultdict(set)
        self.metrics = Metrics()
        self._pending: list[PresenceEvent] = []

    def now(self) -> float:
        return self._now()

    def is_online(self, user_id: str) -> bool:
        """Advertised online: live socket or still inside the grace window."""
        return any(sid in self.sessions for sid in self.sessions_by_user.get(user_id, ()))

    def device_count(self, user_id: str) -> int:
        return sum(
            1
            for sid in self.sessions_by_user.get(user_id, ())
            if (s := self.sessions.get(sid)) and s.grace_until is None
        )

    def connect(self, user_id: str, device: str = "web") -> Session:
        if user_id not in self.users:
            raise KeyError(f"unknown user {user_id}")
        now = self.now()
        live_before = any(
            (s := self.sessions.get(sid)) and s.grace_until is None
            for sid in self.sessions_by_user.get(user_id, ())
        )
        in_grace = any(
            (s := self.sessions.get(sid)) and s.grace_until is not None
            for sid in self.sessions_by_user.get(user_id, ())
        )

        session = Session(
            session_id=str(uuid.uuid4()),
            user_id=user_id,
            device=device,
            connected_at=now,
            last_heartbeat=now,
        )
        self.sessions[session.session_id] = session
        self.sessions_by_user[user_id].add(session.session_id)
        self.subscribe(user_id)
        self.metrics.connects += 1

        if in_grace and not live_before:
            # Contacts never saw the drop. Do not publish a second "online".
            self._clear_grace(user_id)
            self.metrics.grace_saves += 1
            self.metrics.suppressed_flaps += 1
        elif not live_before:
            self._emit(user_id, True, EventReason.CONNECT, now)
        return session

    def heartbeat(self, session_id: str) -> Session:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError("unknown session")
        session.last_heartbeat = self.now()
        session.grace_until = None
        self.metrics.heartbeats += 1
        return session

    def begin_disconnect(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if not session:
            return
        now = self.now()
        session.grace_until = now + GRACE_DISCONNECT_S
        self.metrics.disconnects += 1
        # Do not fan out yet — wait for grace or a reconnect.

    def kill_session(self, session_id: str) -> None:
        """Phone-died path: no close frame, just stop existing."""
        session = self.sessions.get(session_id)
        if not session:
            return
        # Force TTL to have already elapsed relative to last beat.
        session.last_heartbeat = self.now() - SESSION_TTL_S - 0.01
        session.grace_until = None

    def set_privacy(self, user_id: str, last_seen: str, online: str) -> None:
        user = self.users[user_id]
        user.privacy = PrivacySettings(
            last_seen=Visibility(last_seen),
            online=Visibility(online),
        )
        self._emit(user_id, self.is_online(user_id), EventReason.PRIVACY_CHANGED, self.now())

    def subscribe(self, watcher_id: str, targets: list[str] | None = None) -> None:
        watch = set(targets) if targets is not None else self.contacts.get(watcher_id, set())
        for target in watch:
            if watcher_id in self.contacts.get(target, ()):
                self.users[target].watchers.add(watcher_id)

    def unsubscribe_session_owner(self, user_id: str) -> None:
        if self.device_count(user_id) > 0:
            return
        for record in self.users.values():
            record.watchers.discard(user_id)

    def visible_presence(self, viewer_id: str, target_id: str) -> PresenceView:
        target = self.users[target_id]
        online = self.is_online(target_id)
        hide_online = not self._allowed(target.privacy.online, target_id, viewer_id)
        hide_last = not self._allowed(target.privacy.last_seen, target_id, viewer_id)
        # Reciprocity: if the viewer hides last seen, they cannot read others'.
        if viewer_id != target_id:
            viewer = self.users[viewer_id]
            if viewer.privacy.last_seen == Visibility.NOBODY:
                hide_last = True
        return PresenceView(
            user_id=target_id,
            name=target.name,
            online=None if hide_online else online,
            last_seen=None if hide_last else (None if online else target.last_seen),
            hidden_last_seen=hide_last,
            hidden_online=hide_online,
            devices=self.device_count(target_id) if not hide_online else 0,
        )

    def roster_for(self, viewer_id: str) -> list[PresenceView]:
        contacts = sorted(self.contacts.get(viewer_id, set()))
        return [self.visible_presence(viewer_id, cid) for cid in contacts]

    def tick(self) -> list[PresenceEvent]:
        now = self.now()
        self.metrics.ticks += 1
        for sid, session in list(self.sessions.items()):
            if session.grace_until is not None and now >= session.grace_until:
                self.metrics.grace_expiries += 1
                self._drop_session(sid, EventReason.GRACE_EXPIRED, now)
            elif session.grace_until is None and now - session.last_heartbeat > SESSION_TTL_S:
                self.metrics.ttl_expiries += 1
                self._drop_session(sid, EventReason.TTL_EXPIRED, now)
        return self.drain_events()

    def drain_events(self) -> list[PresenceEvent]:
        events, self._pending = self._pending, []
        self.metrics.fanout_messages += sum(len(e.recipients) for e in events)
        return events

    def sessions_snapshot(self) -> list[dict]:
        now = self.now()
        out = []
        for session in self.sessions.values():
            age = now - session.last_heartbeat
            out.append(
                {
                    "session_id": session.session_id,
                    "user_id": session.user_id,
                    "name": self.users[session.user_id].name,
                    "device": session.device,
                    "last_heartbeat_age_s": round(age, 2),
                    "in_grace": session.grace_until is not None,
                    "ttl_remaining_s": round(max(SESSION_TTL_S - age, 0), 2)
                    if session.grace_until is None
                    else 0,
                }
            )
        return out

    def _allowed(self, visibility: Visibility, owner_id: str, viewer_id: str) -> bool:
        if owner_id == viewer_id:
            return True
        if visibility == Visibility.EVERYONE:
            return True
        if visibility == Visibility.NOBODY:
            return False
        return viewer_id in self.contacts.get(owner_id, ())

    def _clear_grace(self, user_id: str) -> None:
        dead: list[str] = []
        for sid in list(self.sessions_by_user.get(user_id, ())):
            session = self.sessions.get(sid)
            if session and session.grace_until is not None:
                dead.append(sid)
        for sid in dead:
            self._remove_session_only(sid)

    def _drop_session(self, session_id: str, reason: EventReason, now: float) -> None:
        session = self.sessions.get(session_id)
        if not session:
            return
        user_id = session.user_id
        self._remove_session_only(session_id)
        if not self.is_online(user_id):
            record = self.users[user_id]
            record.last_seen = session.last_heartbeat
            self.unsubscribe_session_owner(user_id)
            self._emit(user_id, False, reason, now)

    def _remove_session_only(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if not session:
            return
        bucket = self.sessions_by_user[session.user_id]
        bucket.discard(session_id)

    def _emit(self, user_id: str, online: bool, reason: EventReason, at: float) -> None:
        recipients = tuple(
            wid
            for wid in self.users[user_id].watchers
            if wid != user_id and self._should_notify(wid, user_id)
        )
        last_seen = None if online else self.users[user_id].last_seen
        self._pending.append(
            PresenceEvent(
                user_id=user_id,
                online=online,
                last_seen=last_seen,
                reason=reason,
                at=at,
                recipients=recipients,
            )
        )
        self.metrics.history.append(
            {
                "user_id": user_id,
                "name": self.users[user_id].name,
                "online": online,
                "reason": reason.value,
                "at": at,
                "recipients": len(recipients),
            }
        )
        if len(self.metrics.history) > 80:
            self.metrics.history = self.metrics.history[-80:]

    def _should_notify(self, watcher_id: str, target_id: str) -> bool:
        del target_id
        return self.device_count(watcher_id) > 0
