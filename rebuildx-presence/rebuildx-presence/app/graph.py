"""Seeded bidirectional contact graph — the fanout universe."""

from __future__ import annotations

from app.models import PrivacySettings, UserRecord, Visibility

SEED_USERS: dict[str, dict] = {
    "u_dhara": {"name": "Dhara", "avatar": "DH"},
    "u_arjun": {"name": "Arjun", "avatar": "AR"},
    "u_meera": {"name": "Meera", "avatar": "ME"},
    "u_kabir": {"name": "Kabir", "avatar": "KB"},
    "u_zara": {"name": "Zara", "avatar": "ZR"},
    "u_vihaan": {"name": "Vihaan", "avatar": "VH"},
    "u_ananya": {"name": "Ananya", "avatar": "AN"},
    "u_ravi": {"name": "Ravi", "avatar": "RV"},
}

# Bidirectional edges. Not a complete mesh — realistic "phone book" sparsity.
CONTACT_EDGES: list[tuple[str, str]] = [
    ("u_dhara", "u_arjun"),
    ("u_dhara", "u_meera"),
    ("u_dhara", "u_kabir"),
    ("u_dhara", "u_zara"),
    ("u_dhara", "u_vihaan"),
    ("u_dhara", "u_ananya"),
    ("u_arjun", "u_meera"),
    ("u_arjun", "u_kabir"),
    ("u_meera", "u_ananya"),
    ("u_kabir", "u_zara"),
    ("u_zara", "u_vihaan"),
    ("u_vihaan", "u_ravi"),
    ("u_ananya", "u_ravi"),
    ("u_ravi", "u_dhara"),
]


def adjacency() -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {uid: set() for uid in SEED_USERS}
    for a, b in CONTACT_EDGES:
        graph[a].add(b)
        graph[b].add(a)
    return graph


def seed_records() -> dict[str, UserRecord]:
    return {
        uid: UserRecord(
            user_id=uid,
            name=meta["name"],
            avatar=meta["avatar"],
            privacy=PrivacySettings(
                last_seen=Visibility.CONTACTS,
                online=Visibility.CONTACTS,
            ),
        )
        for uid, meta in SEED_USERS.items()
    }
