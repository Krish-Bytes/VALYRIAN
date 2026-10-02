"""Tunable presence timings. These are the knobs you defend in the viva."""

# Client target interval. WhatsApp-class apps typically sit in the 8–30s range
# on mobile to balance radio wakeups vs freshness.
HEARTBEAT_INTERVAL_S = 8.0

# A session dies after this many seconds without a heartbeat. Sized at ~3
# missed beats so one dropped packet does not flap the user offline.
SESSION_TTL_S = 25.0

# After a clean (or unclean) socket close, wait this long before publishing
# "offline". Covers network flaps and app backgrounding with fast reconnect.
GRACE_DISCONNECT_S = 6.0

# Collapse bursty reconnect/disconnect into one fanout event.
FANOUT_COALESCE_S = 0.2

# Sweep interval for TTL / grace expiry. Independent of heartbeats.
TICK_INTERVAL_S = 0.5
