# Technical defense — PS-14 Presence

Judges will ask why this is not "just WebSockets". Steer every answer back to **load, accuracy, and failure modes**.

## 1. Why heartbeats exist

TCP `close` is not a liveness signal. A phone that loses power, a radio that stalls, or a NAT that drops the mapping will not send a FIN. The server only knows the user is gone when **heartbeats stop** and **TTL expires**.

Interval 8s / TTL 25s is a deliberate 3-miss hysteresis: one lost packet must not flap millions of contact lists.

## 2. Grace is not the same as TTL

| Path | Trigger | Delay | Why |
| --- | --- | --- | --- |
| Grace | Socket close / airplane | 6s | Fast reconnect after app switch |
| TTL | Silent death | 25s | No close frame at all |

If you collapse these into one timer, either flaps spam the graph or corpses stay "online" too long.

## 3. Fanout, not polling

Polling: every online user asks for N contacts every interval → `users × contacts × (1/interval)` reads.

This design: invert the graph. Each user has **watchers** = online contacts who subscribed. A presence edge change is `O(watchers)`, typically tens, not millions.

Control-room `polling_equivalent` vs `fanout_messages` is the exhibit.

## 4. Multi-device

WhatsApp is not 1:1 with a socket. Laptop + phone means **union of sessions**. Last seen is written only when the **last** live session dies.

## 5. Privacy

- `online` and `last_seen` are separate (WhatsApp can show "online" while hiding last seen).
- Last-seen **reciprocity**: if you hide yours, you do not read others'. That is a product rule, not an accident of the data model.

## 6. What we would add in production

- Redis HASH + EXPIRE per session, keyspace notifications or a sweeper for TTL
- Sticky fanout via pub/sub (`presence:{user}` → watcher gateways)
- Coalesce bursts (200ms) at the gateway
- Regional presence caches with last-write-wins timestamps
- Backoff heartbeats when the app is backgrounded (longer TTL, slightly staler last seen)

## 7. Attacks / abuse (code review)

- Authenticate hello (this demo seeds users)
- Rate-limit heartbeats
- Do not let clients forge another user's presence
- Watchers must be actual contacts (enforced in `subscribe`)

## 8. Test evidence

`tests/test_presence.py` freezes time. That is how you prove TTL and grace without sleeping 25 seconds in CI.
