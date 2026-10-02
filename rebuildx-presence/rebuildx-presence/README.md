# RebuildX PS-14 — WhatsApp Last Seen

Presence system that answers **who is actually online** without polling every contact.

## Run

```bash
cd rebuildx-presence
py -3 -m pip install -r requirements.txt
py -3 -m pytest -q
py -3 run.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Sign in as **Dhara**, then open a second window as **Arjun**.

## Demo script (3 minutes)

1. Both windows show each other **online** after connect — a push, not a refresh.
2. On Dhara, click **Phone dies**. Heartbeats stop. After the TTL window (~25s, accelerated by a forced miss) Arjun sees **last seen**.
3. Reconnect Dhara. Click **Airplane mode**, then **Reconnect** within 6 seconds. Arjun should **not** flicker offline (grace save).
4. Set Dhara last seen to **Nobody**. Arjun loses last seen; reciprocity means Dhara also cannot read others' last seen.
5. Point at the control room: fanout messages vs polling equivalent.

## How it works

| Problem | Mechanism |
| --- | --- |
| Confirm still connected | Client heartbeat every 8s |
| Detect phone dying (no TCP FIN) | Session TTL 25s (~3 missed beats) |
| Detect socket close / airplane | 6s grace, then last-seen stamp |
| Network flap | Reconnect inside grace → no offline fanout |
| Multi-device | User stays online while any session is live |
| Scale / server load | Push only to **online contact-watchers** |
| Privacy | last-seen / online visibility + last-seen reciprocity |

The engine in `app/presence.py` has no sockets. Redis `# SET user:session EX 25` is the production mapping of the same TTL.

## Layout

- `app/presence.py` — sessions, TTL, grace, privacy, fanout
- `app/main.py` — FastAPI + WebSocket adapter
- `web/` — WhatsApp-style client + judge control room
- `tests/test_presence.py` — clock-controlled unit tests
- `DEFENSE.md` — viva / code-review talking points
