const THREADS = {
  u_arjun: [
    ["in", "Demo the TTL miss first — that's the phone-dies case."],
    ["out", "Then airplane mode so they see the grace window."],
  ],
  u_meera: [
    ["in", "Are we pushing presence or polling?"],
    ["out", "Push to watchers only. Contacts who aren't connected get nothing."],
  ],
  u_kabir: [
    ["in", "What if I am on web and phone together?"],
    ["out", "Online until the last live session expires."],
  ],
  u_zara: [
    ["in", "Last seen nobody — does online still show?"],
    ["out", "They are independent privacy knobs. Reciprocity applies to last seen."],
  ],
  u_vihaan: [
    ["in", "How delayed is sudden death?"],
    ["out", "At most one TTL window (~25s), not minutes of polling lag."],
  ],
  u_ananya: [
    ["in", "Network flap?"],
    ["out", "Grace period swallows the offline event if we reconnect fast."],
  ],
  u_ravi: [
    ["in", "Why not Redis in the demo?"],
    ["out", "The engine is storage-agnostic. TTL keys map 1:1 onto Redis EXPIRE."],
  ],
};

const state = {
  me: null,
  roster: [],
  selected: null,
  ws: null,
  sessionId: null,
  heartbeatTimer: null,
  seq: 0,
  paused: false,
  metrics: null,
};

const $ = (id) => document.getElementById(id);

function fmtLastSeen(ts) {
  if (!ts) return "last seen recently";
  const d = new Date(ts * 1000);
  return `last seen today at ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

function presenceText(p) {
  if (!p) return "tap a contact";
  if (p.hidden_online && p.hidden_last_seen) return "last seen not available";
  if (p.online === true) return p.devices > 1 ? `online · ${p.devices} devices` : "online";
  if (p.hidden_last_seen) return "last seen not available";
  return fmtLastSeen(p.last_seen);
}

async function loadIdentities() {
  const res = await fetch("/api/users");
  const data = await res.json();
  const root = $("identities");
  root.innerHTML = "";
  data.users.forEach((u) => {
    const btn = document.createElement("button");
    btn.innerHTML = `<div class="av">${u.avatar}</div><strong>${u.name}</strong><div class="sub">${u.id}</div>`;
    btn.onclick = () => enter(u);
    root.appendChild(btn);
  });
}

function enter(user) {
  state.me = user;
  $("gate").classList.add("hidden");
  $("app").classList.remove("hidden");
  $("me-name").textContent = user.name;
  $("me-avatar").textContent = user.avatar;
  connect();
}

function connect() {
  clearInterval(state.heartbeatTimer);
  state.paused = false;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  state.ws = ws;
  $("me-status").textContent = "connecting…";

  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "hello", user_id: state.me.id, device: "web" }));
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "hello") onHello(msg);
    if (msg.type === "heartbeat_ack") $("me-status").textContent = "online · heartbeat ok";
    if (msg.type === "presence") onPresence(msg.presence);
    if (msg.type === "roster") {
      state.roster = msg.roster;
      renderRoster();
    }
    if (msg.type === "metrics") renderMetrics(msg);
    if (msg.type === "error" && msg.error === "session_expired") {
      $("me-status").textContent = "session expired (TTL)";
    }
  };
  ws.onclose = () => {
    $("me-status").textContent = "socket closed · grace running on server";
    clearInterval(state.heartbeatTimer);
  };
}

function onHello(msg) {
  state.sessionId = msg.session_id;
  state.roster = msg.roster;
  $("privacy-last").value = msg.privacy.last_seen;
  $("privacy-online").value = msg.privacy.online;
  $("me-status").textContent = "online";
  renderRoster();
  if (!state.selected && state.roster[0]) select(state.roster[0].user_id);
  startHeartbeats(msg.heartbeat_interval_s);
}

function startHeartbeats(intervalS) {
  clearInterval(state.heartbeatTimer);
  state.heartbeatTimer = setInterval(() => {
    if (state.paused || !state.ws || state.ws.readyState !== WebSocket.OPEN) return;
    state.seq += 1;
    state.ws.send(JSON.stringify({ type: "heartbeat", seq: state.seq }));
  }, (intervalS || 8) * 1000);
}

function onPresence(p) {
  const i = state.roster.findIndex((r) => r.user_id === p.user_id);
  if (i >= 0) state.roster[i] = { ...state.roster[i], ...p };
  else state.roster.push(p);
  renderRoster();
  if (state.selected === p.user_id) renderThread(p);
}

function renderRoster() {
  const ul = $("chats");
  ul.innerHTML = "";
  state.roster.forEach((p) => {
    const li = document.createElement("li");
    if (state.selected === p.user_id) li.classList.add("active");
    const on = p.online === true;
    li.innerHTML = `
      <div class="avatar">${p.avatar || "?"}</div>
      <div class="meta">
        <strong>${p.name} ${p.hidden_online ? "" : `<span class="dot ${on ? "on" : ""}"></span>`}</strong>
        <div class="sub">${presenceText(p)}</div>
      </div>`;
    li.onclick = () => select(p.user_id);
    ul.appendChild(li);
  });
}

function select(id) {
  state.selected = id;
  const p = state.roster.find((r) => r.user_id === id);
  renderRoster();
  renderThread(p);
}

function renderThread(p) {
  if (!p) return;
  $("peer-name").textContent = p.name;
  $("peer-avatar").textContent = p.avatar || "?";
  $("peer-presence").textContent = presenceText(p);
  const msgs = THREADS[p.user_id] || [["in", "Presence updates will land in the header — not as chat spam."]];
  $("thread").innerHTML = msgs
    .map(([dir, text]) => `<div class="bubble ${dir}">${text}</div>`)
    .join("");
}

function renderMetrics(m) {
  state.metrics = m;
  $("stats").innerHTML = [
    ["Heartbeats", m.heartbeats],
    ["Fanout msgs", m.fanout_messages],
    ["Poll equivalent", m.polling_equivalent],
    ["Saved", `${Math.round((m.bytes_saved_ratio || 0) * 100)}%`],
    ["TTL deaths", m.ttl_expiries],
    ["Grace saves", m.grace_saves],
  ]
    .map(([k, v]) => `<div class="stat"><b>${v}</b><span>${k}</span></div>`)
    .join("");
  $("sessions").innerHTML = (m.sessions_detail || [])
    .map(
      (s) =>
        `<li>${s.name} · ${s.device} · beat ${s.last_heartbeat_age_s}s ago · TTL ${s.ttl_remaining_s}s${s.in_grace ? " · GRACE" : ""}</li>`
    )
    .join("") || "<li>no live sessions</li>";
  $("history").innerHTML = (m.history || [])
    .slice()
    .reverse()
    .map((h) => `<li>${h.name} → ${h.online ? "online" : "offline"} (${h.reason}) · ${h.recipients} recipients</li>`)
    .join("") || "<li>no events yet</li>";
}

$("btn-dead").onclick = () => {
  state.paused = true;
  if (state.ws?.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ type: "kill" }));
  }
  $("me-status").textContent = "heartbeats stopped · waiting for TTL";
};

$("btn-air").onclick = () => {
  state.ws?.close();
  $("me-status").textContent = "airplane mode";
};

$("btn-re").onclick = () => connect();

function sendPrivacy() {
  if (state.ws?.readyState !== WebSocket.OPEN) return;
  state.ws.send(
    JSON.stringify({
      type: "privacy",
      last_seen: $("privacy-last").value,
      online: $("privacy-online").value,
    })
  );
}
$("privacy-last").onchange = sendPrivacy;
$("privacy-online").onchange = sendPrivacy;

loadIdentities();
