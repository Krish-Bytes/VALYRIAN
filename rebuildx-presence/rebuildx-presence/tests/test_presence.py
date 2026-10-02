from app.config import GRACE_DISCONNECT_S, SESSION_TTL_S
from app.presence import PresenceEngine
from tests import FakeClock


def _engine() -> tuple[PresenceEngine, FakeClock]:
    clock = FakeClock()
    return PresenceEngine(clock=clock), clock


def test_user_is_online_after_connect():
    engine, _ = _engine()
    engine.connect("u_dhara")
    engine.subscribe("u_arjun")
    assert engine.is_online("u_dhara")


def test_heartbeat_refreshes_ttl():
    engine, clock = _engine()
    session = engine.connect("u_dhara")
    clock.advance(SESSION_TTL_S - 1)
    engine.heartbeat(session.session_id)
    clock.advance(SESSION_TTL_S - 1)
    engine.tick()
    assert engine.is_online("u_dhara")


def test_missed_heartbeats_mark_offline_and_stamp_last_seen():
    engine, clock = _engine()
    session = engine.connect("u_dhara")
    beat_time = session.last_heartbeat
    clock.advance(SESSION_TTL_S + 0.1)
    events = engine.tick()
    assert not engine.is_online("u_dhara")
    assert engine.users["u_dhara"].last_seen == beat_time
    assert any(e.reason.value == "ttl_expired" for e in events)


def test_socket_close_uses_grace_then_offline():
    engine, clock = _engine()
    session = engine.connect("u_dhara")
    engine.drain_events()
    engine.begin_disconnect(session.session_id)
    assert engine.is_online("u_dhara")
    clock.advance(GRACE_DISCONNECT_S - 0.2)
    assert engine.tick() == []
    assert session.session_id in engine.sessions
    clock.advance(0.5)
    events = engine.tick()
    assert not engine.is_online("u_dhara")
    assert any(e.reason.value == "grace_expired" for e in events)


def test_reconnect_within_grace_does_not_fanout_offline():
    engine, clock = _engine()
    engine.connect("u_arjun")
    engine.subscribe("u_arjun")
    session = engine.connect("u_dhara")
    engine.subscribe("u_dhara")
    engine.drain_events()
    engine.begin_disconnect(session.session_id)
    clock.advance(1.0)
    engine.connect("u_dhara", device="phone")
    events = engine.drain_events()
    assert engine.is_online("u_dhara")
    assert events == []
    assert engine.metrics.grace_saves == 1
    assert engine.metrics.suppressed_flaps == 1


def test_multi_device_stays_online_if_one_phone_dies():
    engine, clock = _engine()
    phone = engine.connect("u_dhara", device="phone")
    engine.connect("u_dhara", device="web")
    engine.kill_session(phone.session_id)
    clock.advance(0.1)
    engine.tick()
    assert engine.is_online("u_dhara")
    assert engine.device_count("u_dhara") == 1


def test_fanout_only_to_online_contacts_not_strangers():
    engine, _ = _engine()
    engine.connect("u_arjun")
    engine.subscribe("u_arjun")
    # ravi is a contact of dhara; zara is not a contact of ravi
    engine.connect("u_ravi")
    engine.subscribe("u_ravi")
    engine.drain_events()
    engine.connect("u_dhara")
    events = engine.drain_events()
    assert len(events) == 1
    recipients = set(events[0].recipients)
    assert "u_arjun" in recipients
    assert "u_ravi" in recipients
    assert "u_zara" not in recipients


def test_privacy_nobody_hides_last_seen_and_is_reciprocal():
    engine, clock = _engine()
    dhara = engine.connect("u_dhara")
    engine.connect("u_arjun")
    engine.kill_session(dhara.session_id)
    clock.advance(0.1)
    engine.tick()
    engine.set_privacy("u_dhara", last_seen="nobody", online="contacts")
    view = engine.visible_presence("u_arjun", "u_dhara")
    assert view.hidden_last_seen
    assert view.last_seen is None
    view_back = engine.visible_presence("u_dhara", "u_arjun")
    assert view_back.hidden_last_seen


def test_polling_equivalent_dwarfs_fanout():
    engine, _ = _engine()
    engine.connect("u_dhara")
    engine.subscribe("u_dhara")
    engine.connect("u_arjun")
    engine.subscribe("u_arjun")
    for _ in range(50):
        sid = next(iter(engine.sessions_by_user["u_dhara"]))
        engine.heartbeat(sid)
    snap = engine.metrics.snapshot(online_users=2, sessions=2, contacts=28)
    assert snap["fanout_messages"] < snap["polling_equivalent"]
    assert snap["bytes_saved_ratio"] > 0.9
