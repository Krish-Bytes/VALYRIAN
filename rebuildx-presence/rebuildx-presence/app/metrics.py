"""In-memory metrics used to prove the design beats polling."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Metrics:
    heartbeats: int = 0
    connects: int = 0
    disconnects: int = 0
    ttl_expiries: int = 0
    grace_expiries: int = 0
    grace_saves: int = 0
    fanout_messages: int = 0
    suppressed_flaps: int = 0
    ticks: int = 0
    history: list[dict] = field(default_factory=list)

    def snapshot(self, *, online_users: int, sessions: int, contacts: int) -> dict:
        # Naive polling: every online viewer asks for every contact every heartbeat interval.
        # Even a conservative model (8s poll × contacts) dwarfs event fanout.
        polling_equivalent = max(self.heartbeats, 1) * max(contacts, 1)
        saved = max(polling_equivalent - self.fanout_messages, 0)
        ratio = (saved / polling_equivalent) if polling_equivalent else 0.0
        return {
            "heartbeats": self.heartbeats,
            "connects": self.connects,
            "disconnects": self.disconnects,
            "ttl_expiries": self.ttl_expiries,
            "grace_expiries": self.grace_expiries,
            "grace_saves": self.grace_saves,
            "fanout_messages": self.fanout_messages,
            "suppressed_flaps": self.suppressed_flaps,
            "ticks": self.ticks,
            "online_users": online_users,
            "sessions": sessions,
            "polling_equivalent": polling_equivalent,
            "bytes_saved_ratio": round(ratio, 4),
        }
