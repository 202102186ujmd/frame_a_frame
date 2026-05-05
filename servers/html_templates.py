"""
html_templates.py – HTML content served by the index route.

The viewer keeps the last captured frame visible at all times; state
overlays are drawn *on top of* the image without hiding it.
"""

from __future__ import annotations

INDEX_HTML: str = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Frame‑a‑Frame – Drones</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      background: #0d1117;
      color: #e6edf3;
      font-family: 'Segoe UI', system-ui, sans-serif;
      min-height: 100vh;
    }

    header {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 14px 24px;
      background: #161b22;
      border-bottom: 1px solid #30363d;
    }
    header h1 { font-size: 1.15rem; font-weight: 600; }
    #ws-indicator {
      margin-left: auto;
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 0.78rem;
      color: #8b949e;
    }
    #ws-dot {
      width: 9px; height: 9px;
      border-radius: 50%;
      background: #da3633;
      transition: background 0.3s;
    }
    #ws-dot.connected { background: #3fb950; }

    main {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(480px, 1fr));
      gap: 20px;
      padding: 24px;
    }

    .drone-card {
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 10px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }

    .card-header {
      display: flex;
      align-items: center;
      padding: 10px 14px;
      gap: 10px;
      background: #1c2128;
      border-bottom: 1px solid #30363d;
    }
    .card-header h2 { font-size: 0.95rem; font-weight: 600; flex: 1; }

    /* State badge */
    .state-badge {
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      padding: 2px 8px;
      border-radius: 20px;
      background: #30363d;
      color: #8b949e;
      transition: background 0.3s, color 0.3s;
    }
    .state-badge.online    { background: #1a4731; color: #3fb950; }
    .state-badge.offline   { background: #4a1c1c; color: #f85149; }
    .state-badge.stale     { background: #3d2f00; color: #d29922; }
    .state-badge.error     { background: #4a1c1c; color: #f85149; }
    .state-badge.connecting{ background: #162032; color: #58a6ff; }

    /* Video wrapper – position relative so overlay sits on top */
    .video-wrapper {
      position: relative;
      width: 100%;
      aspect-ratio: 16/9;
      background: #000;
      overflow: hidden;
    }

    .drone-img {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: contain;
      /* Never hidden – always shows the last captured frame */
    }

    /* Overlay shown over the image when not online */
    .state-overlay {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 8px;
      background: rgba(0, 0, 0, 0.55);
      opacity: 0;
      transition: opacity 0.35s;
      pointer-events: none;
    }
    .state-overlay.visible { opacity: 1; pointer-events: auto; }

    .overlay-icon { font-size: 2.5rem; }
    .overlay-label {
      font-size: 0.85rem;
      font-weight: 600;
      color: #e6edf3;
      text-align: center;
      padding: 0 12px;
    }
    .overlay-msg {
      font-size: 0.72rem;
      color: #8b949e;
      text-align: center;
      padding: 0 16px;
      max-width: 90%;
    }

    /* No-frame placeholder (before any frame arrives) */
    .placeholder {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #30363d;
      font-size: 0.85rem;
    }

    .card-footer {
      padding: 6px 14px;
      font-size: 0.7rem;
      color: #6e7681;
      background: #1c2128;
      border-top: 1px solid #30363d;
      min-height: 26px;
    }
  </style>
</head>
<body>

<header>
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
       stroke="#58a6ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
  </svg>
  <h1>Frame‑a‑Frame · Drone Monitor</h1>
  <div id="ws-indicator">
    <div id="ws-dot"></div>
    <span id="ws-label">Conectando...</span>
  </div>
</header>

<main id="grid"></main>

<script>
// ──────────────────────────────────────────────────────────────
//  Drone list – populated dynamically from /status endpoint
// ──────────────────────────────────────────────────────────────

const STATE_META = {
  online:     { icon: '✅', label: 'En línea',    overlay: false },
  connecting: { icon: '🔄', label: 'Conectando…', overlay: true  },
  offline:    { icon: '📡', label: 'Sin señal',   overlay: true  },
  stale:      { icon: '⏳', label: 'Sin frames',  overlay: true  },
  error:      { icon: '⚠️', label: 'Error',        overlay: true  },
};

// Per-drone DOM references
const droneCards = {};

// ── Build card DOM ────────────────────────────────────────────
function buildCard(droneId) {
  const card = document.createElement('div');
  card.className = 'drone-card';
  card.id = `card-${droneId}`;

  const meta = STATE_META['connecting'];

  card.innerHTML = `
    <div class="card-header">
      <h2>🚁 ${droneId}</h2>
      <span class="state-badge connecting" id="badge-${droneId}">Conectando</span>
    </div>
    <div class="video-wrapper">
      <div class="placeholder" id="placeholder-${droneId}">Sin frames aún...</div>
      <img class="drone-img" id="img-${droneId}" src="" alt="Frame ${droneId}" style="display:none;" />
      <div class="state-overlay visible" id="overlay-${droneId}">
        <div class="overlay-icon" id="overlay-icon-${droneId}">${meta.icon}</div>
        <div class="overlay-label" id="overlay-label-${droneId}">${meta.label}</div>
        <div class="overlay-msg"   id="overlay-msg-${droneId}"></div>
      </div>
    </div>
    <div class="card-footer" id="footer-${droneId}">Esperando primer frame…</div>
  `;

  document.getElementById('grid').appendChild(card);

  droneCards[droneId] = {
    badge:   document.getElementById(`badge-${droneId}`),
    img:     document.getElementById(`img-${droneId}`),
    overlay: document.getElementById(`overlay-${droneId}`),
    icon:    document.getElementById(`overlay-icon-${droneId}`),
    label:   document.getElementById(`overlay-label-${droneId}`),
    msg:     document.getElementById(`overlay-msg-${droneId}`),
    footer:  document.getElementById(`footer-${droneId}`),
    placeholder: document.getElementById(`placeholder-${droneId}`),
    hasFrame: false,
    lastFrameTime: null,
  };
}

// ── Update state ──────────────────────────────────────────────
function applyState(droneId, state, msg) {
  const c = droneCards[droneId];
  if (!c) return;

  const meta = STATE_META[state] || STATE_META['error'];

  // Badge
  c.badge.textContent = meta.label;
  c.badge.className = `state-badge ${state}`;

  // Overlay: show when not online BUT keep image visible underneath
  c.icon.textContent  = meta.icon;
  c.label.textContent = meta.label;
  c.msg.textContent   = msg || '';

  if (meta.overlay) {
    c.overlay.classList.add('visible');
  } else {
    c.overlay.classList.remove('visible');
  }
}

// ── Update frame ──────────────────────────────────────────────
function applyFrame(droneId, b64data) {
  const c = droneCards[droneId];
  if (!c) return;

  // Show image (replaces placeholder)
  if (!c.hasFrame) {
    c.hasFrame = true;
    c.placeholder.style.display = 'none';
    c.img.style.display = 'block';
  }

  // Update the <img> src – keep previous frame visible until new one loads
  const blob = b64ToBlob(b64data, 'image/jpeg');
  const oldSrc = c.img.src;
  c.img.src = URL.createObjectURL(blob);
  if (oldSrc && oldSrc.startsWith('blob:')) {
    URL.revokeObjectURL(oldSrc);
  }

  c.lastFrameTime = Date.now();
  c.footer.textContent = `Último frame: ${new Date().toLocaleTimeString()}`;
}

function b64ToBlob(b64, mime) {
  const bytes = atob(b64);
  const arr = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
  return new Blob([arr], { type: mime });
}

// ── WebSocket ─────────────────────────────────────────────────
let wsRetryDelay = 1000;
const wsDot   = document.getElementById('ws-dot');
const wsLabel = document.getElementById('ws-label');

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.addEventListener('open', () => {
    wsDot.className = 'connected';
    wsLabel.textContent = 'Conectado';
    wsRetryDelay = 1000;
  });

  ws.addEventListener('message', (ev) => {
    let data;
    try { data = JSON.parse(ev.data); } catch { return; }

    if (!droneCards[data.drone]) {
      buildCard(data.drone);
    }

    if (data.type === 'frame') {
      applyFrame(data.drone, data.data);
    } else if (data.type === 'status') {
      applyState(data.drone, data.state, data.msg);
    }
  });

  ws.addEventListener('close', () => {
    wsDot.className = '';
    wsLabel.textContent = `Reconectando en ${Math.round(wsRetryDelay / 1000)}s...`;
    setTimeout(connectWS, wsRetryDelay);
    wsRetryDelay = Math.min(wsRetryDelay * 2, 30_000);
  });

  ws.addEventListener('error', () => ws.close());
}

// ── Bootstrap ─────────────────────────────────────────────────
async function init() {
  try {
    const res  = await fetch('/status');
    const list = await res.json();
    for (const d of list) {
      buildCard(d.drone);
      applyState(d.drone, d.state, d.msg);
    }
  } catch {
    // If /status fails, cards will be built on first WS message
  }
  connectWS();
}

init();
</script>
</body>
</html>
"""
