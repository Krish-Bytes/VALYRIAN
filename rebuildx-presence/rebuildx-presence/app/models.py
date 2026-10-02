from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class Visibility(str, Enum):
    EVERYONE = "everyone"
    CONTACTS = "contacts"
    NOBODY = "nobody"


class DisconnectReason(str, Enum):
    GRACEFUL = "graceful"
    SOCKET_CLOSE = "socket_close"
    TTL_MISS = "ttl_miss"
    KILLED = "killed"


class EventReason(str, Enum):
    CONNECT = "connect"
    HEARTBEAT = "heartbeat"
    RECONNECT_WITHIN_GRACE = "reconnect_within_grace"
    GRACE_EXPIRED = "grace_expired"
    TTL_EXPIRED = "ttl_expired"
    LAST_SESSION_LEFT = "last_session_left"
    PRIVACY_CHANGED = "privacy_changed"


@dataclass
class PrivacySettings:
    last_seen: Visibility = Visibility.CONTACTS
    online: Visibility = Visibility.CONTACTS


@dataclass
class Session:
    session_id: str
    user_id: str
    device: str
    connected_at: float
    last_heartbeat: float
    grace_until: float | None = None


@dataclass
class UserRecord:
    user_id: str
    name: str
    avatar: str
    last_seen: float | None = None
    privacy: PrivacySettings = field(default_factory=PrivacySettings)
    watchers: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class PresenceView:
    user_id: str
    name: str
    online: bool | None
    last_seen: float | None
    hidden_last_seen: bool
    hidden_online: bool
    devices: int


@dataclass(frozen=True)
class PresenceEvent:
    user_id: str
    online: bool
    last_seen: float | None
    reason: EventReason
    at: float
    recipients: tuple[str, ...]


WsOpcode = Literal[
    "hello",
    "heartbeat",
    "heartbeat_ack",
    "presence",
    "roster",
    "metrics",
    "error",
    "privacy",
    "kill",
    "pause_heartbeats",
]
