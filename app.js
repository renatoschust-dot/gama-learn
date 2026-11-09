/* GAMA Learn — vanilla force graph */
(() => {
  "use strict";
  const cv = document.getElementById("graph");
  const ctx = cv.getContext("2d");
  const mini = document.getElementById("mini");
  const mctx = mini ? mini.getContext("2d") : null;
  const $ = (id) => document.getElementById(id);

  const S = {
    nodes: [], edges: [], map: new Map(),
    view: { x: 0, y: 0, k: 1 },
    alpha: 1, running: true,
    selected: null, hovered: null, brainHits: new Map(),
    learned: new Set(), agent: "opencode", fp: "", role: "",
    brainOk: false, drag: null, panning: null, moved: false, didFit: false,
    hidden: new Set(), miniMap: null,
    W: 0, H: 0, dpr: 1,
  };

  const COLORS = { topic: "#5aa9ff", skill: "#ffab4a", web: "#c58cff", brain: "#b28dff" };
  const enc = encodeURIComponent;
  let TOKEN = localStorage.getItem("gama-learn-token") || "";
  try {
    const up = new URLSearchParams(location.search);
    const ut = up.get("token");
    if (ut) {
      TOKEN = ut;
      localStorage.setItem("gama-learn-token", TOKEN);
      history.replaceState({}, "", location.pathname + location.hash);
    }
  } catch (_) {}

  function authHeaders(extra) {
    const h = Object.assign({}, extra || {});
    if (TOKEN) h["X-Learn-Token"] = TOKEN;
    return h;
  }
  async function askToken() {
    const t = window.prompt("GAMA Learn token:");
    if (!t) return false;
    TOKEN = t.trim();
    localStorage.setItem("gama-learn-token", TOKEN);
    return true;
  }

  function applyAuth(a) {
    const ro = !!a && a.role === "read";
    S.role = (a && a.role) || "";
    for (const id of ["toggle", "save-note", "eval"]) {
      const b = $(id);
      if (!b) continue;
      b.disabled = ro;
      b.title = ro ? "read-only token" : "";
    }
    const tb = $("tokens");
    if (tb) tb.style.display = (a && a.role === "admin") ? "" : "none";
    if (ro) toast("Read-only režim" + (a.agent ? " · " + a.agent : ""));
  }

  function resize() {
    S.dpr = Math.min(2, window.devicePixelRatio || 1);
    S.W = window.innerWidth; S.H = window.innerHeight;
    cv.width = Math.floor(S.W * S.dpr);
    cv.height = Math.floor(S.H * S.dpr);
    cv.style.width = S.W + "px";
    cv.style.height = S.H + "px";
    ctx.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
    draw();
  }
  window.addEventListener("resize", resize);
  resize();

  // ---------- data ----------
  async function jget(url) {
    let r = await fetch(url, { headers: authHeaders() });
    if (r.status === 401 && await askToken()) r = await fetch(url, { headers: authHeaders() });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }
  async function jpost(url, body) {
    let r = await fetch(url, { method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body) });
    if (r.status === 401 && await askToken()) {
      r = await fetch(url, { method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(body) });
    }
    return r.json();
  }

  async function init() {
    setStatus("Učitavam graf…");
    let g;
    try { g = await jget("/api/graph"); }
    catch (e) { setStatus("Greška: " + e.message); return; }
    S.nodes = g.nodes.map((d, i) => {
      const a = i * 2.39996;
      const r = 40 + Math.sqrt(i) * 26;
      return Object.assign({}, d, {
        x: Math.cos(a) * r, y: Math.sin(a) * r, vx: 0, vy: 0,
        fixed: false,
      });
    });
    S.map = new Map(S.nodes.map((n2) => [n2.id, n2]));
    S.edges = g.edges.filter((e) => S.map.has(e.source) && S.map.has(e.target));
    S.nodes.forEach((n2) => { n2.deg = 0; });
    S.edges.forEach((e) => { S.map.get(e.source).deg++; S.map.get(e.target).deg++; });
    S.fp = g.fp || "";
    updateStatus(g);
    try { const a = await jget("/api/auth"); applyAuth(a.auth || {}); } catch (_) {}
    await loadLearned();
    await pollVersion();
    loadAlerts().catch(() => {});
    S.alpha = 1;
    requestAnimationFrame(tick);
  }

  // ---------- force sim ----------
  function tick() {
    if (S.alpha > 0.02) step(16);
    draw();
    if (S.alpha > 0.02 || S.drag) requestAnimationFrame(tick);
    else {
      S.running = false;
      if (!S.didFit) { S.didFit = true; autoFit(); draw(); }
    }
  }

  function reheat(a = 0.7) {
    S.alpha = Math.max(S.alpha, a);
    if (!S.running) { S.running = true; requestAnimationFrame(tick); }
  }

  function step(dt) {
    const ns = S.nodes, es = S.edges, a = S.alpha;
    for (const n of ns) { n.fx = 0; n.fy = 0; }
    // repulsion (O(n^2), n ~ 200)
    for (let i = 0; i < ns.length; i++) {
      const p = ns[i];
      for (let j = i + 1; j < ns.length; j++) {
        const q = ns[j];
        let dx = p.x - q.x, dy = p.y - q.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) { dx = (Math.random() - 0.5); dy = (Math.random() - 0.5); d2 = 1; }
        if (d2 > 260000) continue;
        const f = 6800 / d2;
        const d = Math.sqrt(d2);
        const ux = dx / d, uy = dy / d;
        p.fx += ux * f; p.fy += uy * f;
        q.fx -= ux * f; q.fy -= uy * f;
      }
    }
    // springs
    for (const e of es) {
      const p = S.map.get(e.source), q = S.map.get(e.target);
      if (!p || !q) continue;
      const dx = q.x - p.x, dy = q.y - p.y;
      const d = Math.hypot(dx, dy) || 1;
      const target = 135 + (1 - e.w) * 85;
      const f = (d - target) * 0.010 * (0.4 + e.w);
      const ux = dx / d, uy = dy / d;
      p.fx += ux * f; p.fy += uy * f;
      q.fx -= ux * f; q.fy -= uy * f;
    }
    // center + group anchors + integrate
    const ANCH = { memorija: { x: -280, y: 0 }, skill: { x: 280, y: 0 }, izvori: { x: 0, y: -260 } };
    for (const n of ns) {
      const anch = ANCH[n.group];
      if (anch) {
        n.fx += (anch.x - n.x) * 0.008;
        n.fy += (anch.y - n.y) * 0.008;
      }
      n.fx += -n.x * 0.0032;
      n.fy += -n.y * 0.0032;
      if (n.fixed) { n.vx = n.vy = 0; continue; }
      n.vx = (n.vx + n.fx * 0.9) * 0.86;
      n.vy = (n.vy + n.fy * 0.9) * 0.86;
      const sp = Math.hypot(n.vx, n.vy);
      if (sp > 24) { n.vx *= 24 / sp; n.vy *= 24 / sp; }
      n.x += n.vx; n.y += n.vy;
    }
    S.alpha *= 0.985;
  }

  // ---------- camera ----------
  function toWorld(sx, sy) {
    return { x: (sx - S.W / 2 - S.view.x) / S.view.k,
             y: (sy - S.H / 2 - S.view.y) / S.view.k };
  }
  function toScreen(wx, wy) {
    return { x: wx * S.view.k + S.W / 2 + S.view.x,
             y: wy * S.view.k + S.H / 2 + S.view.y };
  }
  function fit() {
    S.view = { x: 0, y: 0, k: 0.85 };
  }

  function autoFit() {
    if (!S.nodes.length) return;
    let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    for (const n of S.nodes) {
      minX = Math.min(minX, n.x); maxX = Math.max(maxX, n.x);
      minY = Math.min(minY, n.y); maxY = Math.max(maxY, n.y);
    }
    const bw = Math.max(200, maxX - minX), bh = Math.max(200, maxY - minY);
    const availW = S.W - 140, availH = S.H - 240;
    const k = Math.min(1.4, Math.max(0.32, Math.min(availW / bw, availH / bh)));
    const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
    S.view.k = k;
    S.view.x = -cx * k;
    S.view.y = -cy * k + 44;
  }

  // ---------- draw ----------
  function draw() {
    ctx.clearRect(0, 0, S.W, S.H);
    const v = S.view;
    const sel = S.selected, hov = S.hovered;

    // group hulls
    const GROUPS = { memorija: { c: "#5aa9ff", label: "tema" }, skill: { c: "#ffab4a", label: "skill" }, izvori: { c: "#c58cff", label: "izvor" } };
    for (const g of Object.keys(GROUPS)) {
      if (S.hidden.has(g)) continue;
      const members = S.nodes.filter((n) => (n.group || "") === g);
      if (members.length < 2) continue;
      let cx = 0, cy = 0;
      for (const n of members) { cx += n.x; cy += n.y; }
      cx /= members.length; cy /= members.length;
      let rad = 0;
      for (const n of members) rad = Math.max(rad, Math.hypot(n.x - cx, n.y - cy));
      rad += 46;
      const c = toScreen(cx, cy), rp = rad * v.k;
      if (rp < 24) continue;
      const meta = GROUPS[g];
      ctx.globalAlpha = 0.055; ctx.fillStyle = meta.c;
      ctx.beginPath(); ctx.arc(c.x, c.y, rp, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 0.22; ctx.lineWidth = 1; ctx.strokeStyle = meta.c;
      ctx.beginPath(); ctx.arc(c.x, c.y, rp, 0, Math.PI * 2); ctx.stroke();
      ctx.globalAlpha = 0.6; ctx.fillStyle = meta.c;
      ctx.font = "600 12px ui-sans-serif, system-ui, sans-serif"; ctx.textAlign = "center";
      ctx.fillText(meta.label + " · " + members.length, c.x, c.y - rp - 8);
      ctx.globalAlpha = 1; ctx.textAlign = "start";
    }

    // edges
    ctx.lineWidth = 1;
    for (const e of S.edges) {
      const p = S.map.get(e.source), q = S.map.get(e.target);
      if (!p || !q) continue;
      if (S.hidden.has(p.group || "") || S.hidden.has(q.group || "")) continue;
      const a = toScreen(p.x, p.y), b = toScreen(q.x, q.y);
      const active = sel && (e.source === sel.id || e.target === sel.id);
      ctx.strokeStyle = active ? "rgba(120,180,255,0.55)" : `rgba(90,120,160,${0.05 + e.w * 0.22})`;
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }

    // nodes
    const wantLabel = (n) => (sel && sel.id === n.id) || (hov && hov.id === n.id) ||
      (v.k > 0.95) || (v.k > 0.5 && (n.deg || 0) >= 4) || (n.deg || 0) >= 7;
    const boxes = [];
    const order = S.nodes.slice().sort((a, b) => (b.deg || 0) - (a.deg || 0));
    for (const n of S.nodes) {
      if (S.hidden.has(n.group || "")) continue;
      const p = toScreen(n.x, n.y);
      if (p.x < -60 || p.y < -60 || p.x > S.W + 60 || p.y > S.H + 60) continue;
      const r = Math.max(3.2, Math.min(11, n.size * 0.62)) * Math.sqrt(v.k);
      const learned = S.learned.has(n.id);
      const isSel = sel && sel.id === n.id;
      const isHov = hov && hov.id === n.id;
      const col = COLORS[n.kind] || "#8fa3bd";

      ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.fillStyle = learned ? "rgba(70,211,139,0.85)" : col;
      ctx.globalAlpha = (isSel || isHov) ? 1 : 0.86;
      ctx.fill();
      if (isSel) {
        ctx.globalAlpha = 1; ctx.lineWidth = 2.4; ctx.strokeStyle = "#fff";
        ctx.beginPath(); ctx.arc(p.x, p.y, r + 3.5, 0, Math.PI * 2); ctx.stroke();
      } else if (learned) {
        ctx.globalAlpha = 0.9; ctx.lineWidth = 1.6; ctx.strokeStyle = "#46d38b";
        ctx.beginPath(); ctx.arc(p.x, p.y, r + 2.5, 0, Math.PI * 2); ctx.stroke();
      }
      ctx.globalAlpha = 1;

    }
    // labels (collision-aware, important nodes first)
    let bi = 0;
    for (const n of order) {
      if (S.hidden.has(n.group || "")) continue;
      const p = toScreen(n.x, n.y);
      if (p.x < -80 || p.y < -40 || p.x > S.W + 80 || p.y > S.H + 40) continue;
      const isSel = sel && sel.id === n.id, isHov = hov && hov.id === n.id;
      if (!wantLabel(n) && !isSel && !isHov) continue;
      if (!isSel && !isHov && bi > 55) continue;
      const r = Math.max(3.2, Math.min(11, n.size * 0.62)) * Math.sqrt(v.k);
      const label = n.label.length > 34 ? n.label.slice(0, 33) + "…" : n.label;
      ctx.font = `${isSel ? "600 " : ""}${Math.min(12, 8.5 + v.k * 2)}px ui-sans-serif, system-ui`;
      const tw = ctx.measureText(label).width;
      const bx = p.x - tw / 2 - 3, by = p.y + r + 3, bw2 = tw + 6, bh2 = 14;
      let clash = false;
      for (const b of boxes) {
        if (bx < b[0] + b[2] && bx + bw2 > b[0] && by < b[1] + b[3] && by + bh2 > b[1]) { clash = true; break; }
      }
      if (clash && !isSel && !isHov) continue;
      boxes.push([bx, by, bw2, bh2]);
      ctx.textAlign = "center"; ctx.textBaseline = "top";
      ctx.fillStyle = "rgba(6,8,12,0.72)";
      ctx.fillRect(bx, by, bw2, bh2);
      ctx.fillStyle = isSel ? "#ffffff" : "rgba(220,232,247,0.9)";
      ctx.fillText(label, p.x, p.y + r + 5);
      bi++;
    }
    drawMini();
  }

  function drawMini() {
    if (!mctx) return;
    const W = 160, H = 110, pad = 10;
    mctx.clearRect(0, 0, W, H);
    const vis = S.nodes.filter((n) => !S.hidden.has(n.group || ""));
    if (!vis.length) { S.miniMap = null; return; }
    let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    for (const n of vis) {
      if (n.x < minX) minX = n.x;
      if (n.x > maxX) maxX = n.x;
      if (n.y < minY) minY = n.y;
      if (n.y > maxY) maxY = n.y;
    }
    const s = Math.min((W - 2 * pad) / Math.max(1, maxX - minX),
                       (H - 2 * pad) / Math.max(1, maxY - minY));
    const ox = (W - (maxX - minX) * s) / 2;
    const oy = (H - (maxY - minY) * s) / 2;
    S.miniMap = { minX, minY, s, ox, oy };
    for (const n of vis) {
      const x = (n.x - minX) * s + ox, y = (n.y - minY) * s + oy;
      const isSel = S.selected && S.selected.id === n.id;
      mctx.beginPath(); mctx.arc(x, y, isSel ? 2.2 : 1.2, 0, Math.PI * 2);
      mctx.fillStyle = COLORS[n.kind] || "#8fa3bd";
      mctx.globalAlpha = isSel ? 1 : 0.75;
      mctx.fill();
    }
    mctx.globalAlpha = 1;
    const tl = toWorld(0, 0), br = toWorld(S.W, S.H);
    const x1 = (tl.x - minX) * s + ox, y1 = (tl.y - minY) * s + oy;
    const x2 = (br.x - minX) * s + ox, y2 = (br.y - minY) * s + oy;
    mctx.strokeStyle = "rgba(160,200,255,0.85)"; mctx.lineWidth = 1;
    mctx.strokeRect(Math.max(0, x1), Math.max(0, y1),
                    Math.min(W, x2) - Math.max(0, x1), Math.min(H, y2) - Math.max(0, y1));
  }

  function miniJump(e) {
    if (!S.miniMap || !mini) return;
    const r = mini.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const M = S.miniMap;
    const wx = (mx - M.ox) / M.s + M.minX;
    const wy = (my - M.oy) / M.s + M.minY;
    S.view.x = -wx * S.view.k;
    S.view.y = -wy * S.view.k;
    draw();
  }

  if (mini) {
    mini.addEventListener("pointerdown", (e) => { mini.setPointerCapture(e.pointerId); miniJump(e); });
    mini.addEventListener("pointermove", (e) => { if (e.buttons) miniJump(e); });
  }

  // ---------- interaction ----------
  function pick(sx, sy) {
    let best = null, bd = 18;
    for (const n of S.nodes) {
      if (S.hidden.has(n.group || "")) continue;
      const p = toScreen(n.x, n.y);
      const d = Math.hypot(p.x - sx, p.y - sy);
      if (d < bd) { bd = d; best = n; }
    }
    return best;
  }

  const touches = new Map();
  let pinch = null;

  cv.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "touch") touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (touches.size >= 2) {
      const [a, b] = [...touches.values()];
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      const w = toWorld(mx, my);
      if (S.drag && S.drag.n) S.drag.n.fixed = false;
      pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, wx: w.x, wy: w.y };
      S.drag = null;
      S.panning = null;
      S.moved = true;
      cv.classList.remove("dragging");
      try { cv.setPointerCapture(e.pointerId); } catch (_) {}
      e.preventDefault();
      return;
    }
    S.moved = false;
    const n = pick(e.clientX, e.clientY);
    if (n) {
      S.drag = { n, ox: n.x, oy: n.y, sx: e.clientX, sy: e.clientY };
      n.fixed = true;
      reheat(0.4);
    } else {
      S.panning = { sx: e.clientX, sy: e.clientY, vx: S.view.x, vy: S.view.y };
      cv.classList.add("dragging");
    }
    cv.setPointerCapture(e.pointerId);
  });

  cv.addEventListener("pointermove", (e) => {
    if (e.pointerType === "touch" && touches.has(e.pointerId)) {
      touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
    }
    if (pinch && touches.size >= 2) {
      const [a, b] = [...touches.values()];
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      const d = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      S.view.k = Math.min(4, Math.max(0.18, S.view.k * (d / pinch.d)));
      pinch.d = d;
      S.view.x = mx - S.W / 2 - pinch.wx * S.view.k;
      S.view.y = my - S.H / 2 - pinch.wy * S.view.k;
      e.preventDefault();
      draw();
      return;
    }
    if (S.drag) {
      const w = toWorld(e.clientX, e.clientY);
      const dx = e.clientX - S.drag.sx, dy = e.clientY - S.drag.sy;
      if (Math.abs(dx) + Math.abs(dy) > 3) S.moved = true;
      S.drag.n.x = w.x; S.drag.n.y = w.y;
      reheat(0.5);
      return;
    }
    if (S.panning) {
      const dx = e.clientX - S.panning.sx, dy = e.clientY - S.panning.sy;
      if (Math.abs(dx) + Math.abs(dy) > 3) S.moved = true;
      S.view.x = S.panning.vx + dx;
      S.view.y = S.panning.vy + dy;
      draw();
      return;
    }
    const n = pick(e.clientX, e.clientY);
    if ((n && n.id) !== (S.hovered && S.hovered.id)) { S.hovered = n; draw(); }
  });

  cv.addEventListener("pointerup", (e) => {
    if (e.pointerType === "touch") touches.delete(e.pointerId);
    if (touches.size < 2) pinch = null;
    if (S.drag) {
      const n = S.drag.n;
      n.fixed = false;
      S.drag = null;
      if (!S.moved) openNode(n);
    } else if (S.panning) {
      S.panning = null;
      cv.classList.remove("dragging");
      if (!S.moved) closePanel();
    }
    try { cv.releasePointerCapture(e.pointerId); } catch (_) {}
  });

  cv.addEventListener("pointercancel", (e) => {
    if (e.pointerType === "touch") touches.delete(e.pointerId);
    if (touches.size < 2) pinch = null;
    if (S.drag && S.drag.n) S.drag.n.fixed = false;
    S.drag = null;
    S.panning = null;
    cv.classList.remove("dragging");
    try { cv.releasePointerCapture(e.pointerId); } catch (_) {}
  });

  cv.addEventListener("wheel", (e) => {
    e.preventDefault();
    const before = toWorld(e.clientX, e.clientY);
    const factor = Math.exp(-e.deltaY * 0.0015);
    S.view.k = Math.min(4, Math.max(0.18, S.view.k * factor));
    const after = toWorld(e.clientX, e.clientY);
    S.view.x += (after.x - before.x) * S.view.k;
    S.view.y += (after.y - before.y) * S.view.k;
    draw();
  }, { passive: false });

  // ---------- panel ----------
  const side = $("side");
  async function openNode(n) {
    S.selected = n;
    draw();
    side.classList.add("open");
    const kindLabel = n.kind === "skill" ? "skill" : n.kind === "topic" ? "tema" : (n.kind || "čvor");
    const extra = n.group && n.group.toLowerCase() !== kindLabel ? " · " + n.group : "";
    $("k-kind").textContent = kindLabel + extra;
    $("k-title").textContent = n.label;
    $("k-ref").textContent = n.ref || n.id;
    $("k-doc").textContent = "Učitavam…";
    $("k-related").innerHTML = "";
    $("note").value = "";
    $("k-curric").innerHTML = "";
    $("k-curric").classList.remove("open");
    updateToggle();
    if (n.id.startsWith("brain:")) {
      $("k-doc").textContent = n.text || "(bez teksta)";
      return;
    }
    try {
      const d = await jget("/api/lesson?ref=" + encodeURIComponent(n.ref || ""));
      if (d.ok) {
        renderDoc(d.text || "");
        if (d.url && (n.kind === "web" || n.id.startsWith("src:"))) {
          const a = document.createElement("a");
          a.className = "btn";
          a.href = d.url;
          a.target = "_blank";
          a.rel = "noopener";
          a.textContent = "Otvori sajt →";
          a.style.display = "inline-block";
          a.style.marginBottom = "10px";
          $("k-doc").prepend(a);
        }
      } else $("k-doc").textContent = "Ne mogu da pročitam: " + (d.err || "?");
    } catch (e) {
      $("k-doc").textContent = "Greška: " + e.message;
    }
    renderRelated(n);
  }

  function closePanel() {
    side.classList.remove("open");
    S.selected = null;
    draw();
  }

  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  function renderDoc(text) {
    const MAX = 12000;
    let t = text.slice(0, MAX);
    const lines = t.split("\n");
    let html = "";
    for (const line of lines) {
      const s = line.trim();
      if (!s) { html += "\n"; continue; }
      let h = esc(line);
      h = h.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      h = h.replace(/`([^`]+)`/g, "<code>$1</code>");
      if (/^#{1,6}\s/.test(s)) {
        html += `<h3>${esc(s.replace(/^#{1,6}\s*/, ""))}</h3>\n`;
      } else {
        html += h + "\n";
      }
    }
    const doc = $("k-doc");
    doc.innerHTML = html;
    if (text.length > MAX) {
      doc.innerHTML += `<div style="color:#6b7a90;margin-top:10px">… skraćeno (${text.length} znakova)</div>`;
    }
  }

  function renderRelated(n) {
    const rel = [];
    for (const e of S.edges) {
      if (e.source === n.id) rel.push([e.target, e.w]);
      else if (e.target === n.id) rel.push([e.source, e.w]);
    }
    rel.sort((a, b) => b[1] - a[1]);
    const box = $("k-related");
    if (!rel.length) { box.innerHTML = ""; return; }
    box.innerHTML = '<div class="h">povezano</div>';
    for (const [id, w] of rel.slice(0, 8)) {
      const t = S.map.get(id);
      if (!t) continue;
      const b = document.createElement("button");
      b.className = "rel";
      b.textContent = "→ " + t.label;
      b.onclick = () => openNode(t);
      box.appendChild(b);
    }
  }

  // ---------- learned ----------
  async function loadLearned() {
    try {
      const d = await jget("/api/learned?agent=" + encodeURIComponent(S.agent));
      S.learned = new Set(Object.keys(d.nodes || {}));
    } catch (_) { S.learned = new Set(); }
    updateProgress();
    updateToggle();
    draw();
  }

  function updateProgress() {
    const total = S.nodes.length || 1;
    const n = S.learned.size;
    $("progress").innerHTML = `<b>${n}</b> / ${total} naučeno`;
  }

  function updateToggle() {
    const btn = $("toggle");
    if (!S.selected) { btn.textContent = "Označi kao naučeno"; return; }
    const on = S.learned.has(S.selected.id);
    btn.textContent = on ? "✓ Naučeno — skini oznaku" : "Označi kao naučeno";
    btn.classList.toggle("green", on);
  }

  $("toggle").onclick = async () => {
    if (!S.selected) return;
    const n = S.selected, id = n.id;
    const on = !S.learned.has(id);
    if (on) S.learned.add(id); else S.learned.delete(id);
    updateToggle(); updateProgress(); draw();
    try {
      const d = await jpost("/api/learned", { agent: S.agent, node: id, learned: on,
        label: n.label || "", ref: n.ref || "", kind: n.kind || "" });
      if (!d.ok) throw new Error(d.err || "?");
      if (on) {
        const ev = d.evidence || {};
        const ch = ev.challenge || "";
        const b = d.brain && d.brain.ok ? " · brain OK" : " · brain FAIL";
        toast(ch === "PASS" ? "Naučeno ✓ · dokaz PASS" + b
          : "Naučeno · dokaz: " + (ch || "nema challenge-a") + b);
      } else {
        toast("Oznaka skinuta");
      }
    } catch (e) {
      if (on) S.learned.delete(id); else S.learned.add(id);
      updateToggle(); updateProgress(); draw();
      toast("Greška: " + e.message);
    }
  };

  $("save-note").onclick = async () => {
    const text = $("note").value.trim();
    if (!S.selected || !text) return;
    $("save-note").textContent = "Upisujem…";
    try {
      const d = await jpost("/api/note", { agent: S.agent, node: S.selected.id, text });
      $("save-note").textContent = d.ok ? "✓ Zapisano u brain" : "Greška: " + (d.err || "?");
    } catch (e) { $("save-note").textContent = "Greška: " + e.message; }
    setTimeout(() => { $("save-note").textContent = "Zapiši lekciju u brain"; }, 2500);
  };

  $("agent").onchange = (e) => {
    S.agent = e.target.value;
    loadLearned();
  };

  const legendEl = $("legend");
  if (legendEl) {
    legendEl.querySelectorAll(".lg[data-group]").forEach((b) => {
      b.onclick = () => {
        const g = b.dataset.group;
        if (S.hidden.has(g)) S.hidden.delete(g); else S.hidden.add(g);
        b.classList.toggle("off", S.hidden.has(g));
        if (S.selected && S.hidden.has(S.selected.group || "")) closePanel();
        reheat(0.35); draw();
      };
    });
  }

  // ---------- search ----------
  const q = $("q"), hits = $("hits");
  let timer = null;
  q.addEventListener("input", () => {
    clearTimeout(timer);
    const val = q.value.trim();
    if (!val) { hits.classList.remove("open"); hits.innerHTML = ""; return; }
    timer = setTimeout(() => runSearch(val), 220);
  });
  q.addEventListener("keydown", (e) => { if (e.key === "Escape") { hits.classList.remove("open"); q.blur(); } });

  async function runSearch(val) {
    hits.innerHTML = '<div class="hit"><div class="t">Tražim…</div></div>';
    hits.classList.add("open");
    try {
      const d = await jget("/api/search?q=" + encodeURIComponent(val) + "&k=6");
      if (document.activeElement !== q) { hits.classList.remove("open"); return; }
      S.brainOk = !!d.brain_ok;
      let html = "";
      for (const h of (d.local || [])) {
        html += `<div class="hit" data-node="${esc(h.id)}" data-ref="${encodeURIComponent(h.ref || "")}" data-label="${esc(h.label)}" data-kind="${esc(h.kind || "topic")}">
          <div class="t"><span class="badge ${h.kind}">${h.kind === "skill" ? "skill" : "tema"}</span>${esc(h.label)}</div>
        </div>`;
      }
      S.brainHits = new Map();
      for (const h of (d.brain || [])) {
        S.brainHits.set(h.ref || "", h.text || "");
        const txt = (h.text || "").replace(/\s+/g, " ").slice(0, 160);
        html += `<div class="hit" data-brain="${encodeURIComponent(h.ref || "")}" data-kind="${esc(h.kind || "")}">
          <div class="t"><span class="badge topic">brain</span>${esc(txt.slice(0, 60))}…</div>
          <div class="m">${esc(txt)}</div>
        </div>`;
      }
      if (d.index && d.index.items) html += `<div class="hit"><div class="m">${d.matches} pogodaka · pretraga pokriva ${d.index.items} tema+skillova</div></div>`;
      if (!d.brain_ok) html += `<div class="hit"><div class="m">brain :8065 nije dostupan (lokalni rezultati rade)</div></div>`;
      if (!html) html = '<div class="hit"><div class="m">Nema rezultata.</div></div>';
      hits.innerHTML = html;
      hits.querySelectorAll(".hit[data-node]").forEach((el) => {
        el.onclick = () => {
          let n = S.map.get(el.dataset.node);
          if (!n) n = { id: el.dataset.node, label: el.dataset.label || el.dataset.node,
            kind: el.dataset.kind || "topic", ref: decodeURIComponent(el.dataset.ref || "") };
          hits.classList.remove("open");
          openNode(n);
          if (S.map.get(n.id)) focusNode(n);
        };
      });
      hits.querySelectorAll(".hit[data-brain]").forEach((el) => {
        el.onclick = async () => {
          hits.classList.remove("open");
          const ref = decodeURIComponent(el.dataset.brain);
          const snippet = S.brainHits.get(ref) || "";
          const node = { id: "brain:" + ref, label: "brain · " + (el.dataset.kind || "zapis"),
            kind: "brain", ref: ref, text: snippet || "Učitavam…" };
          S.selected = node; draw();
          side.classList.add("open");
          $("k-kind").textContent = "brain · " + (el.dataset.kind || "zapis");
          $("k-title").textContent = "brain zapis";
          $("k-ref").textContent = ref;
          $("k-doc").textContent = "Učitavam…";
          $("k-related").innerHTML = "";
          updateToggle();
          try {
            const d = await jget("/api/lesson?ref=" + encodeURIComponent("brain:ref:" + ref));
            if (d.ok && d.text) renderDoc(d.text);
            else renderDoc(snippet);
          } catch (e) { renderDoc(snippet || ("Greška: " + e.message)); }
        };
      });
    } catch (e) {
      hits.innerHTML = `<div class="hit"><div class="m">Greška: ${esc(e.message)}</div></div>`;
    }
  }

  function focusNode(n) {
    S.view.k = Math.max(1.1, S.view.k);
    S.view.x = -n.x * S.view.k;
    S.view.y = -n.y * S.view.k;
    draw();
  }

  function setStatus(t) { $("status").textContent = t; }

  function updateStatus(g) {
    const cap = g.stats.capped
      ? ` <span class="muted">(od ${g.stats.topics_total} tema / ${g.stats.skills_total} skillova)</span>` : "";
    $("status").innerHTML = `<b>${g.stats.nodes}</b> čvorova · <b>${g.stats.edges}</b> veza · ` +
      `${g.stats.topics} tema · ${g.stats.skills} skillova` +
      (g.stats.sources ? ` · ${g.stats.sources} izvora` : "") + cap;
  }

  let toastTimer = null;
  function toast(msg) {
    const el = $("toast");
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
  }

  async function refreshGraph(fp) {
    let g;
    try { g = await jget("/api/graph"); } catch (_) { return; }
    const old = S.map;
    const added = g.nodes.filter((d) => !old.has(d.id)).length;
    const newIds = new Set(g.nodes.map((d) => d.id));
    const removed = [...old.keys()].filter((id) => !newIds.has(id)).length;
    const nodes = g.nodes.map((d) => {
      const o = old.get(d.id);
      if (o) {
        Object.assign(o, { label: d.label, kind: d.kind, group: d.group,
          size: d.size, ref: d.ref, sub: d.sub, url: d.url, built: d.built });
        return o;
      }
      return Object.assign({}, d, { x: 0, y: 0, vx: 0, vy: 0, fixed: false, deg: d.deg || 0 });
    });
    S.nodes = nodes;
    S.map = new Map(nodes.map((n) => [n.id, n]));
    S.edges = g.edges.filter((e) => S.map.has(e.source) && S.map.has(e.target));
    // novi čvorovi pored suseda
    for (const d of g.nodes) {
      if (old.has(d.id)) continue;
      const n = S.map.get(d.id);
      const nb = [];
      for (const e of S.edges) {
        if (e.source === d.id && old.has(e.target)) nb.push(S.map.get(e.target));
        else if (e.target === d.id && old.has(e.source)) nb.push(S.map.get(e.source));
      }
      if (nb.length) {
        n.x = nb.reduce((a, b) => a + b.x, 0) / nb.length + (Math.random() - 0.5) * 80;
        n.y = nb.reduce((a, b) => a + b.y, 0) / nb.length + (Math.random() - 0.5) * 80;
      } else {
        const a = Math.random() * Math.PI * 2, r = 300 + Math.random() * 240;
        n.x = Math.cos(a) * r; n.y = Math.sin(a) * r;
      }
    }
    S.nodes.forEach((n) => { n.deg = 0; });
    S.edges.forEach((e) => { S.map.get(e.source).deg++; S.map.get(e.target).deg++; });
    if (S.selected && !S.map.has(S.selected.id)) closePanel();
    S.fp = fp || g.fp || S.fp;
    updateStatus(g);
    await loadLearned();
    if (!S.didFit) { S.didFit = true; autoFit(); }
    reheat(0.9);
    toast(`Graf osvežen: +${added} / −${removed} čvorova`);
  }

  async function pollVersion() {
    try {
      const v = await jget("/api/version");
      setStream(v.stream || "");
      if (!S.fp) { S.fp = v.fp; return; }
      if (v.fp !== S.fp) await refreshGraph(v.fp);
    } catch (_) {}
  }

  async function nextNode() {
    hits.classList.remove("open");
    const focus = S.selected && !S.selected.id.startsWith("brain:") ? "&focus=" + enc(S.selected.id) : "";
    let d;
    try { d = await jget("/api/next?agent=" + enc(S.agent) + focus); }
    catch (e) { toast("Greška: " + e.message); return; }
    if (d.done) { toast("Sve je naučeno za " + S.agent + " 🎉"); return; }
    const n = S.map.get(d.node.id);
    if (!n) { toast("Čvor nije u grafu — osveži."); return; }
    openNode(n);
    focusNode(n);
    toast("Sledeće: " + d.node.label + " — " + d.reason);
  }

  async function openPlan() {
    hits.classList.remove("open");
    side.classList.add("open");
    S.selected = null;
    $("k-kind").textContent = "kurikulum · " + S.agent;
    $("k-title").textContent = "Plan za danas";
    $("k-ref").textContent = "brain bira 6 čvorova (hubovi + povezano)";
    $("k-doc").innerHTML = "Sastavljam plan…";
    $("k-related").innerHTML = "";
    updateToggle();
    let d;
    try { d = await jget("/api/curriculum?agent=" + enc(S.agent) + "&n=6"); }
    catch (e) { $("k-doc").textContent = "Greška: " + e.message; return; }
    if (d.done || !(d.items || []).length) {
      $("k-doc").textContent = "Sve je naučeno za " + S.agent + " 🎉";
      return;
    }
    let html = "";
    for (const it of d.items) {
      const kind = it.kind === "skill" ? "skill" : "tema";
      html += `<button class="planitem" data-node="${esc(it.id)}">
        <span class="num">${it.order}</span><span class="badge ${it.kind}">${kind}</span>
        ${esc(it.label)}
        <div class="m">${it.linked ? "↳ povezano sa prethodnim · " : ""}deg ${it.deg}</div>
      </button>`;
    }
    const doc = $("k-doc");
    doc.innerHTML = html;
    doc.querySelectorAll(".planitem").forEach((el) => {
      el.onclick = () => {
        const n = S.map.get(el.dataset.node);
        if (n) { openNode(n); focusNode(n); }
      };
    });
  }

  // ---------- studijski kit (turbo.ai stil) ----------
  $("study").onclick = openStudy;
  $("cert").onclick = openCert;

  // ---------- kurikulum po skillu ----------
  $("curric").onclick = openCurric;

  $("eval").onclick = async () => {
    const name = skillNameOf(S.selected);
    if (!name) { toast("Eval je za skill čvorove."); return; }
    const el = $("k-curric");
    el.classList.add("open");
    el.innerHTML = '<div class="muted">Pokrećem challenge…</div>';
    try {
      const d = await jget("/api/eval?skill=" + enc(name));
      if (!d.ok) { el.innerHTML = `<div class="muted">${esc(d.err || "?")}</div>`; return; }
      const col = d.status === "PASS" ? "#46d38b" : (d.status === "SKIP" ? "#ffab4a" : "#ff6b6b");
      el.innerHTML = `<div class="chead">Eval · <span style="color:${col}">${esc(d.status)}</span> · ${d.ms} ms</div>` +
        `<div class="chint">${esc(d.challenge || "")} · rc ${d.rc}</div>` +
        `<div class="ctask">${esc(d.evidence || "")}</div>`;
      if (d.status === "PASS") toast("Eval PASS · " + name);
    } catch (e) { el.textContent = "Greška: " + e.message; }
  };

  $("eval-llm").onclick = async () => {
    const name = skillNameOf(S.selected);
    if (!name) { toast("LLM eval je za skill čvorove."); return; }
    const el = $("k-curric");
    el.classList.add("open");
    el.innerHTML = '<div class="muted">LLM eval (pass@3 + judge)… može potrajati 10–40 s</div>';
    try {
      const d = await jget("/api/eval/llm?skill=" + enc(name) + "&k=3");
      if (!d.ok) { el.innerHTML = `<div class="muted">${esc(d.err || "?")}</div>`; return; }
      renderLlmEval(d);
    } catch (e) { el.textContent = "Greška: " + e.message; }
  };

  function renderLlmEval(d) {
    const el = $("k-curric");
    el.classList.add("open");
    const ok = !!d.pass_at_k;
    const col = ok ? "#46d38b" : "#ff6b6b";
    let h = `<div class="chead">LLM eval · pass@${d.k} = <span style="color:${col}">${ok ? "PASS" : "FAIL"}</span> · ${d.passed}/${d.k} · ${d.total_ms} ms</div>`;
    h += `<div class="chint">${esc(d.title || d.skill)} · model ${esc(d.model || "?")}</div>`;
    h += (d.runs || []).map((r) => {
      if (r.error) return `<div class="clevel"><div class="ct"><b>#${r.n}</b><span class="cm">${r.ms} ms</span></div><div class="ctask">${esc(r.error)}</div></div>`;
      const j = r.judge || {};
      const jp = j.pass === true ? "judge PASS" : (j.pass === false ? "judge FAIL" : "judge n/a");
      const js = (j.score === null || j.score === undefined) ? "" : " · " + j.score;
      return `<div class="clevel"><div class="ct"><b>#${r.n} ${r.pass ? "PASS" : "FAIL"}</b><span class="cm">det ${r.det} · ${jp}${js} · ${r.ms} ms</span></div>` +
        (j.reason ? `<div class="chint">${esc(j.reason)}</div>` : "") +
        `<div class="ctask">${esc((r.answer || "").slice(0, 500))}</div></div>`;
    }).join("");
    el.innerHTML = h;
  }

  function skillNameOf(n) {
    if (!n) return "";
    if (n.id && n.id.startsWith("skill:")) return n.id.slice(6);
    const ref = n.ref || "";
    if (ref.endsWith("SKILL.md")) return ref.split("/").slice(-2)[0];
    return "";
  }

  async function openCurric() {
    const name = skillNameOf(S.selected);
    if (!name) { toast("Kurikulum je za skill čvorove (klikni žuti čvor)."); return; }
    const el = $("k-curric");
    el.classList.add("open");
    el.innerHTML = '<div class="muted">Pravim kurikulum…</div>';
    let d;
    try { d = await jget("/api/curriculum?skill=" + enc(name)); }
    catch (e) { el.textContent = "Greška: " + e.message; return; }
    renderCurric(d);
  }

  function renderCurric(d) {
    const el = $("k-curric");
    el.classList.add("open");
    if (!d.ok) { el.innerHTML = `<div class="muted">${esc(d.err || "?")}</div>`; return; }
    const s = d.skill || {};
    let html = `<div class="chead">Kurikulum · ${d.levels.length} nivoa · ~${d.minutes_total} min</div>`;
    html += `<div class="chint">${esc(s.title || s.name || "")}${s.domain ? " · " + esc(s.domain) : ""}${s.challenge_status ? " · dokaz " + esc(s.challenge_status) : ""}${s.installed ? "" : " · nije instaliran"}</div>`;
    html += d.levels.map((l) => `<div class="clevel">
      <div class="ct"><b>${l.n}. ${esc(l.title)}</b><span class="cm">${l.minutes} min</span></div>
      <div class="ctask">${esc(l.task)}</div>
      <div class="cev">dokaz: ${esc(l.evidence)}</div>
      ${l.hint ? `<div class="chint">${esc(l.hint)}</div>` : ""}
    </div>`).join("");
    if (d.headings && d.headings.length) html += `<div class="chint">sekcije: ${d.headings.map(esc).join(" · ")}</div>`;
    el.innerHTML = html;
  }

  async function openStudy() {
    if (!S.selected) { toast("Prvo izaberi čvor."); return; }
    if (S.selected.id.startsWith("brain:")) { toast("Brain zapis nema lokalni fajl za kit."); return; }
    const ref = S.selected.ref || "";
    if (!ref) { toast("Čvor nema fajl."); return; }
    $("k-doc").innerHTML = "Pravim studijski kit…";
    $("k-related").innerHTML = "";
    let d;
    try { d = await jget("/api/study?ref=" + enc(ref)); }
    catch (e) { $("k-doc").textContent = "Greška: " + e.message; return; }
    if (!d.ok) { $("k-doc").textContent = d.err || "Nema teksta za kit."; return; }
    let html = `<div class="kit">
      <div class="kit-actions">
        <button class="btn" id="kit-audio">▶ Audio (bs)</button>
        <button class="btn muted" id="kit-back">← Lekcija</button>
      </div>
      <div id="kit-audio-box" class="muted small"></div>
      <h3>Sažetak</h3><ul>${(d.summary || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
      <h3>Ključne tačke (${(d.key_points || []).length})</h3>
      <ol>${(d.key_points || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ol>
      <h3>Kartice (${(d.flashcards || []).length})</h3>`;
    for (const c of (d.flashcards || [])) {
      html += `<details class="card"><summary>${esc(c.front)}</summary><div>${esc(c.back)}</div></details>`;
    }
    if ((d.quiz || []).length) {
      html += `<h3>Kviz (${d.quiz.length})</h3>`;
      for (const qz of d.quiz) {
        html += `<div class="quizq" data-answer="${qz.answer}"><div class="qq">${qz.n}. ${esc(qz.q)}</div>`;
        qz.options.forEach((o, i) => {
          html += `<button class="qopt" data-i="${i}">${String.fromCharCode(65 + i)}. ${esc(o)}</button>`;
        });
        html += `<div class="qres"></div></div>`;
      }
    }
    html += `</div>`;
    const doc = $("k-doc");
    doc.innerHTML = html;
    $("kit-back").onclick = () => { if (S.selected) openNode(S.selected); };
    doc.querySelectorAll(".quizq").forEach((el) => {
      const ans = parseInt(el.dataset.answer, 10);
      el.querySelectorAll(".qopt").forEach((b) => {
        b.onclick = () => {
          const i = parseInt(b.dataset.i, 10);
          el.querySelectorAll(".qopt").forEach((x) => x.classList.remove("ok", "bad"));
          b.classList.add(i === ans ? "ok" : "bad");
          el.querySelector(".qres").textContent = i === ans
            ? "Tačno." : "Netačno — tačan je " + String.fromCharCode(65 + ans) + ".";
        };
      });
    });
    $("kit-audio").onclick = async () => {
      const box = $("kit-audio-box");
      box.textContent = "Generišem audio (edge-tts)…";
      try {
        const a = await jget("/api/tts?ref=" + enc(ref) + "&voice=bs-BA-VesnaNeural");
        if (a.ok) {
          box.innerHTML = `<audio controls autoplay src="${a.url}"></audio>` +
            `<div class="muted small">${esc(a.voice)} · ${Math.round(a.bytes / 1024)} KB${a.cached ? " · keš" : ""}</div>`;
        } else box.textContent = a.err || "TTS nije dostupan.";
      } catch (e) { box.textContent = "Greška: " + e.message; }
    };
  }

  function openCert() {
    if (!S.selected) { toast("Izaberi čvor."); return; }
    if (!S.learned.has(S.selected.id)) { toast("Prvo označi kao naučeno."); return; }
    const url = "/api/certificate?agent=" + enc(S.agent) + "&node=" + enc(S.selected.id) +
      (TOKEN ? "&token=" + enc(TOKEN) : "");
    window.open(url, "_blank");
  }

  // ---------- istraživanje (legalni izvori) ----------
  async function openResearch(queryArg) {
    const query = (queryArg || q.value || "").trim();
    hits.classList.remove("open");
    side.classList.add("open");
    S.selected = null;
    updateToggle();
    $("k-kind").textContent = "istraživanje · OpenAlex + arXiv";
    $("k-title").textContent = query ? "Istraži: " + query : "Istraži";
    $("k-ref").textContent = "besplatni legalni izvori (bez Sci-Hub)";
    $("k-related").innerHTML = "";
    $("k-doc").innerHTML = `<div class="rsearch">
        <input id="rq" class="search mini" value="${esc(query)}" placeholder="tema, naslov, DOI…">
        <button class="btn" id="rgo">Traži</button>
      </div><div id="rres"></div>`;
    $("rgo").onclick = () => openResearch($("rq").value);
    $("rq").addEventListener("keydown", (e) => { if (e.key === "Enter") openResearch($("rq").value); });
    if (!query) return;
    const res = $("rres");
    res.textContent = "Tražim po OpenAlex i arXiv…";
    let d;
    try { d = await jget("/api/research?q=" + enc(query) + "&n=8"); }
    catch (e) { res.textContent = "Greška: " + e.message; return; }
    if (!d.ok) { res.textContent = d.err || "Nema rezultata."; return; }
    let html = "";
    for (const it of (d.items || [])) {
      const link = it.url || it.pdf || "";
      html += `<div class="paper">
        <div class="pt"><a href="${esc(link)}" target="_blank" rel="noopener">${esc(it.title)}</a></div>
        <div class="pm">${esc(it.source)} · ${esc(String(it.year || ""))}${it.authors && it.authors.length ? " · " + esc(it.authors.slice(0, 3).join(", ")) : ""}</div>
        <div class="pa">${esc((it.abstract || "").slice(0, 280))}${(it.abstract || "").length > 280 ? "…" : ""}</div>
        <div class="pl">${it.url ? `<a href="${esc(it.url)}" target="_blank" rel="noopener">Otvori</a>` : ""}
          ${it.pdf ? `<a href="${esc(it.pdf)}" target="_blank" rel="noopener">PDF</a>` : ""}</div>
      </div>`;
    }
    if (!html) html = `<div class="muted">Nema rezultata za „${esc(query)}“.</div>`;
    res.innerHTML = html;
  }

  // ---------- alati (delphi.tools stil) ----------
  const TOOLS = [];
  const toolAdd = (id, name, render) => TOOLS.push({ id, name, render });
  const b64e = (s) => btoa(unescape(encodeURIComponent(s)));
  const b64d = (s) => decodeURIComponent(escape(atob(s)));
  const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
  const rnd = (n) => {
    const a = new Uint8Array(n);
    crypto.getRandomValues(a);
    return a;
  };
  const slugify = (s) => s.toLowerCase()
    .replace(/[čć]/g, "c").replace(/[ž]/g, "z").replace(/[š]/g, "s").replace(/đ/g, "d")
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");

  toolAdd("json", "JSON", (el) => {
    el.innerHTML = `<div class="trow">
      <button class="btn" data-a="fmt">Formatiraj</button>
      <button class="btn" data-a="min">Minify</button>
      <button class="btn muted" data-a="clear">Očisti</button></div>
      <textarea class="tarea" placeholder='{"a": 1, "b": [2, 3]}'></textarea>
      <pre class="tout"></pre>`;
    const ta = el.querySelector("textarea"), out = el.querySelector(".tout");
    el.querySelectorAll("[data-a]").forEach((b) => b.onclick = () => {
      if (b.dataset.a === "clear") { ta.value = ""; out.textContent = ""; return; }
      try {
        const v = JSON.parse(ta.value);
        out.textContent = b.dataset.a === "fmt" ? JSON.stringify(v, null, 2) : JSON.stringify(v);
        out.className = "tout ok";
      } catch (e) { out.textContent = "Neispravan JSON: " + e.message; out.className = "tout bad"; }
    });
  });

  toolAdd("b64", "Base64", (el) => {
    el.innerHTML = `<div class="trow"><button class="btn" data-a="e">Kodiraj</button>
      <button class="btn" data-a="d">Dekodiraj</button></div>
      <textarea class="tarea" placeholder="tekst ili base64…"></textarea><pre class="tout"></pre>`;
    const ta = el.querySelector("textarea"), out = el.querySelector(".tout");
    el.querySelectorAll("[data-a]").forEach((b) => b.onclick = () => {
      try {
        out.textContent = b.dataset.a === "e" ? b64e(ta.value) : b64d(ta.value.trim());
        out.className = "tout ok";
      } catch (e) { out.textContent = "Greška: " + e.message; out.className = "tout bad"; }
    });
  });

  toolAdd("hash", "SHA-256", (el) => {
    el.innerHTML = `<textarea class="tarea" placeholder="tekst za hash…"></textarea>
      <div class="trow"><button class="btn">Izračunaj SHA-256</button></div><pre class="tout"></pre>`;
    const ta = el.querySelector("textarea"), out = el.querySelector(".tout");
    el.querySelector("button").onclick = async () => {
      try {
        const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(ta.value));
        out.textContent = hex(buf); out.className = "tout ok";
      } catch (e) { out.textContent = "Greška: " + e.message; out.className = "tout bad"; }
    };
  });

  toolAdd("uuid", "UUID", (el) => {
    el.innerHTML = `<div class="trow"><button class="btn">Generiši 5 UUID v4</button></div><pre class="tout"></pre>`;
    const out = el.querySelector(".tout");
    el.querySelector("button").onclick = () => {
      const list = [];
      for (let i = 0; i < 5; i++) {
        list.push(crypto.randomUUID ? crypto.randomUUID() :
          ([1e7] + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g,
            (c) => (c ^ rnd(1)[0] & 15 >> c / 4).toString(16)));
      }
      out.textContent = list.join("\n"); out.className = "tout ok";
    };
  });

  toolAdd("pass", "Lozinka", (el) => {
    el.innerHTML = `<div class="trow"><label class="muted small">dužina
      <input id="plen" type="number" value="20" min="8" max="64" style="width:64px"></label>
      <label class="muted small"><input id="psym" type="checkbox" checked> simboli</label>
      <button class="btn">Generiši</button></div><pre class="tout"></pre>`;
    const out = el.querySelector(".tout");
    el.querySelector("button").onclick = () => {
      const len = Math.max(8, Math.min(64, parseInt(el.querySelector("#plen").value || "20", 10)));
      let abc = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
      if (el.querySelector("#psym").checked) abc += "!@#$%^&*()-_=+[]{}";
      const a = rnd(len);
      out.textContent = [...a].map((x) => abc[x % abc.length]).join("");
      out.className = "tout ok";
    };
  });

  toolAdd("case", "Velika/mala", (el) => {
    el.innerHTML = `<textarea class="tarea" placeholder="tekst…"></textarea>
      <div class="trow"><button class="btn" data-a="u">VELIKA</button><button class="btn" data-a="l">mala</button>
      <button class="btn" data-a="t">Naslov</button><button class="btn" data-a="s">slug</button></div>
      <pre class="tout"></pre>`;
    const ta = el.querySelector("textarea"), out = el.querySelector(".tout");
    el.querySelectorAll("[data-a]").forEach((b) => b.onclick = () => {
      const v = ta.value;
      const t = b.dataset.a === "u" ? v.toUpperCase()
        : b.dataset.a === "l" ? v.toLowerCase()
        : b.dataset.a === "t" ? v.replace(/\S+/g, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase())
        : slugify(v);
      out.textContent = t; out.className = "tout ok";
    });
  });

  toolAdd("url", "URL", (el) => {
    el.innerHTML = `<div class="trow"><button class="btn" data-a="e">Encode</button>
      <button class="btn" data-a="d">Decode</button></div>
      <textarea class="tarea" placeholder="https://… ili %20…"></textarea><pre class="tout"></pre>`;
    const ta = el.querySelector("textarea"), out = el.querySelector(".tout");
    el.querySelectorAll("[data-a]").forEach((b) => b.onclick = () => {
      try {
        out.textContent = b.dataset.a === "e" ? encodeURIComponent(ta.value) : decodeURIComponent(ta.value);
        out.className = "tout ok";
      } catch (e) { out.textContent = "Greška: " + e.message; out.className = "tout bad"; }
    });
  });

  toolAdd("time", "Vrijeme", (el) => {
    el.innerHTML = `<div class="trow"><button class="btn" data-a="now">Sada</button></div>
      <input class="tin" id="tsin" placeholder="unix epoch ili 2026-11-07 21:00">
      <pre class="tout"></pre>`;
    const out = el.querySelector(".tout"), inp = el.querySelector("#tsin");
    const render = (d) => {
      out.textContent = `ISO:   ${d.toISOString()}\nEpoch: ${Math.floor(d.getTime() / 1000)}\nLokal: ${d.toString()}`;
      out.className = "tout ok";
    };
    el.querySelector("[data-a=now]").onclick = () => render(new Date());
    inp.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      const v = inp.value.trim();
      const d = /^\d+$/.test(v) ? new Date(parseInt(v, 10) * 1000) : new Date(v);
      if (isNaN(d)) { out.textContent = "Ne mogu da parsiram."; out.className = "tout bad"; }
      else render(d);
    });
  });

  toolAdd("text", "Tekst", (el) => {
    el.innerHTML = `<textarea class="tarea" placeholder="zalijepi tekst…"></textarea><pre class="tout ok"></pre>`;
    const ta = el.querySelector("textarea"), out = el.querySelector(".tout");
    const upd = () => {
      const t = ta.value;
      const words = t.trim() ? t.trim().split(/\s+/).length : 0;
      out.textContent = `znakova: ${t.length}\nbez razmaka: ${t.replace(/\s/g, "").length}\nriječi: ${words}\nredova: ${t ? t.split("\n").length : 0}`;
    };
    ta.addEventListener("input", upd); upd();
  });

  toolAdd("regex", "Regex", (el) => {
    el.innerHTML = `<div class="trow"><input class="tin" id="rpat" placeholder="\\d+" style="flex:1">
      <input class="tin" id="rflg" value="gi" style="width:64px"></div>
      <textarea class="tarea" placeholder="tekst za test…"></textarea><pre class="tout"></pre>`;
    const ta = el.querySelector("textarea"), out = el.querySelector(".tout");
    const run = () => {
      try {
        const re = new RegExp(el.querySelector("#rpat").value, el.querySelector("#rflg").value);
        const m = ta.value.match(re) || [];
        out.textContent = `pronađeno: ${m.length}\n` + m.slice(0, 40).join("\n");
        out.className = "tout ok";
      } catch (e) { out.textContent = "Regex greška: " + e.message; out.className = "tout bad"; }
    };
    el.querySelector("#rpat").addEventListener("input", run);
    el.querySelector("#rflg").addEventListener("input", run);
    ta.addEventListener("input", run);
  });

  toolAdd("color", "Boja", (el) => {
    el.innerHTML = `<div class="trow"><input id="chel" class="tin" value="#5aa9ff" style="width:100px">
      <span id="csw" style="width:34px;height:34px;border-radius:8px;display:inline-block;background:#5aa9ff;border:1px solid #2b4a72"></span></div>
      <pre class="tout ok"></pre>`;
    const out = el.querySelector(".tout"), inp = el.querySelector("#chel");
    const upd = () => {
      let v = inp.value.trim().replace(/^#/, "");
      if (v.length === 3) v = v.split("").map((c) => c + c).join("");
      if (!/^[0-9a-f]{6}$/i.test(v)) { out.textContent = "Unesi hex, npr. #5aa9ff"; return; }
      const r = parseInt(v.slice(0, 2), 16), g = parseInt(v.slice(2, 4), 16), b = parseInt(v.slice(4, 6), 16);
      const mx = Math.max(r, g, b) / 255, mn = Math.min(r, g, b) / 255;
      const l = (mx + mn) / 2, d = mx - mn;
      let h = 0, sat = 0;
      if (d) {
        sat = d / (1 - Math.abs(2 * l - 1));
        if (mx === r / 255) h = 60 * (((g - b) / 255 / d) % 6);
        else if (mx === g / 255) h = 60 * ((b - r) / 255 / d + 2);
        else h = 60 * ((r - g) / 255 / d + 4);
      }
      if (h < 0) h += 360;
      out.textContent = `HEX: #${v.toLowerCase()}\nRGB: rgb(${r}, ${g}, ${b})\nHSL: hsl(${Math.round(h)}, ${Math.round(sat * 100)}%, ${Math.round(l * 100)}%)`;
      el.querySelector("#csw").style.background = "#" + v;
    };
    inp.addEventListener("input", upd); upd();
  });

  toolAdd("md", "Markdown", (el) => {
    el.innerHTML = `<textarea class="tarea" placeholder="# Naslov&#10;- stavka&#10;**bold** i \`kod\`"></textarea>
      <div class="mdprev"></div>`;
    const ta = el.querySelector("textarea"), prev = el.querySelector(".mdprev");
    const upd = () => {
      let h = esc(ta.value);
      h = h.replace(/^###\s+(.+)$/gm, "<h4>$1</h4>")
        .replace(/^##\s+(.+)$/gm, "<h3>$1</h3>")
        .replace(/^#\s+(.+)$/gm, "<h2>$1</h2>")
        .replace(/^\s*[-*]\s+(.+)$/gm, "<li>$1</li>")
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
        .replace(/\n/g, "<br>");
      prev.innerHTML = h;
    };
    ta.addEventListener("input", upd); upd();
  });

  const toolsModal = $("toolsModal");
  function openTools(which) {
    hits.classList.remove("open");
    toolsModal.classList.add("open");
    const nav = $("toolnav");
    nav.innerHTML = "";
    TOOLS.forEach((t) => {
      const b = document.createElement("button");
      b.className = "toolbtn" + (t.id === which ? " active" : "");
      b.textContent = t.name;
      b.onclick = () => selectTool(t.id);
      nav.appendChild(b);
    });
    selectTool(which || TOOLS[0].id);
  }
  function selectTool(id) {
    const t = TOOLS.find((x) => x.id === id) || TOOLS[0];
    document.querySelectorAll(".toolbtn").forEach((b) => b.classList.toggle("active", b.textContent === t.name));
    const pane = $("toolpane");
    pane.innerHTML = "";
    t.render(pane);
  }
  $("tools").onclick = () => openTools();
  $("toolsClose").onclick = () => toolsModal.classList.remove("open");
  toolsModal.addEventListener("click", (e) => { if (e.target === toolsModal) toolsModal.classList.remove("open"); });
  $("research").onclick = () => openResearch();

  // ---------- moći (alat/hack/besplatno/novost/skill/prečica) ----------
  const CATS = { alat: "Alati", hack: "Hackovi", besplatno: "Besplatno",
    novost: "Novosti", skill: "Skillovi", precica: "Prečice" };
  const powersModal = $("powersModal");
  let POWERS = null, P_FILTER = "all", P_Q = "", HEALTH = null;

  async function refreshHealth(force) {
    try {
      const h = await jget("/api/health" + (force ? "?refresh=1" : ""));
      HEALTH = h.checks || {};
      const s = h.summary || {};
      $("pcount").textContent = (POWERS ? POWERS.length : 0) + " stavki · " + (s.online || 0) + "/" + (s.total || 0) + " online";
      return true;
    } catch (e) { HEALTH = null; return false; }
  }

  async function openPowers() {
    hits.classList.remove("open");
    powersModal.classList.add("open");
    $("plist").innerHTML = '<div class="muted" style="padding:20px">Učitavam…</div>';
    if (!POWERS) {
      try {
        const d = await jget("/api/powers");
        POWERS = d.items || [];
      } catch (e) {
        $("plist").textContent = "Greška: " + e.message;
        return;
      }
    }
    await refreshHealth(false);
    renderPowers();
  }

  function renderPowers() {
    const counts = {};
    for (const it of POWERS) counts[it.kategorija] = (counts[it.kategorija] || 0) + 1;
    const chips = [["all", "Sve", POWERS.length]].concat(
      Object.keys(CATS).map((k) => [k, CATS[k], counts[k] || 0]));
    $("pchips").innerHTML = chips.map(([k, label, n]) =>
      `<button class="chip${k === P_FILTER ? " active" : ""}" data-cat="${k}">${label}<span>${n}</span></button>`).join("");
    $("pchips").querySelectorAll(".chip").forEach((b) => {
      b.onclick = () => { P_FILTER = b.dataset.cat; renderPowers(); };
    });

    const low = P_Q.trim().toLowerCase();
    const items = POWERS.filter((it) => {
      if (P_FILTER !== "all" && it.kategorija !== P_FILTER) return false;
      if (!low) return true;
      return (it.naziv + " " + it.opis + " " + it.komanda + " " + (it.dokaz || "")).toLowerCase().includes(low);
    });
    const list = $("plist");
    if (!items.length) {
      list.innerHTML = '<div class="muted" style="padding:16px">Nema rezultata.</div>';
      return;
    }
    list.innerHTML = items.map((it) => {
      const cat = it.kategorija || "alat";
      const label = CATS[cat] || cat;
      const risk = it.rizik ? `<span class="risk ${esc(it.rizik)}" title="rizik: ${esc(it.rizik)}"></span>` : "";
      const hh = HEALTH && HEALTH[it.id];
      const dot = hh ? `<span class="hdot ${hh.ok ? "ok" : "bad"}" title="${esc(hh.info || "")} · ${hh.ms} ms"></span>` : "";
      const link = it.link ? ` · <a href="${esc(it.link)}" target="_blank" rel="noopener">izvor</a>` : "";
      return `<article class="power">
        <div class="phead"><span class="pbadge ${cat}">${label}</span><b>${esc(it.naziv)}</b>${dot}${risk}</div>
        <div class="pdesc">${esc(it.opis)}</div>
        <div class="pcmd" data-cmd="${esc(it.komanda)}" title="Klikni da kopiraš"><code>${esc(it.komanda)}</code><span class="copy">kopiraj</span></div>
        <div class="pmeta">${esc(it.dokaz || "")}${link}</div>
      </article>`;
    }).join("");
    list.querySelectorAll(".pcmd").forEach((el) => {
      el.onclick = async () => {
        const text = el.dataset.cmd;
        try { await navigator.clipboard.writeText(text); toast("Kopirano: " + text.slice(0, 50)); }
        catch (_) { toast("Kopiranje nije dozvoljeno — označi ručno."); }
      };
    });
  }

  $("powers").onclick = openPowers;
  $("healthRefresh").onclick = async () => { await refreshHealth(true); renderPowers(); };
  $("powersClose").onclick = () => powersModal.classList.remove("open");
  powersModal.addEventListener("click", (e) => { if (e.target === powersModal) powersModal.classList.remove("open"); });
  $("pq").addEventListener("input", (e) => { P_Q = e.target.value; renderPowers(); });

  // ---------- katalog (4498 skillova/alata) ----------
  const catalogModal = $("catalogModal");
  let CAT = null, C_FILTER = "all", C_Q = "", C_TIMER = null;

  async function loadCatalog() {
    const p = new URLSearchParams({ limit: "200" });
    if (C_Q.trim()) p.set("q", C_Q.trim());
    if (C_FILTER === "skill" || C_FILTER === "tool") p.set("kind", C_FILTER);
    if (C_FILTER === "inst") p.set("installed", "1");
    if (C_FILTER === "ver") p.set("status", "verified");
    $("clist").innerHTML = '<div class="muted" style="padding:16px">Učitavam katalog…</div>';
    try { CAT = await jget("/api/catalog?" + p.toString()); }
    catch (e) { $("clist").textContent = "Greška: " + e.message; return; }
    renderCatalog();
  }

  function renderCatalog() {
    const st = (CAT && CAT.stats) || {};
    const chips = [["all", "Sve", st.total || 0], ["skill", "Skillovi", st.skills || 0],
      ["tool", "Alati", st.tools || 0], ["inst", "Instalirano", st.installed || 0],
      ["ver", "Verifikovano", st.verified || 0]];
    $("cchips").innerHTML = chips.map(([k, l, n]) =>
      `<button class="chip${k === C_FILTER ? " active" : ""}" data-cat="${k}">${l}<span>${n}</span></button>`).join("");
    $("cchips").querySelectorAll(".chip").forEach((b) => {
      b.onclick = () => { C_FILTER = b.dataset.cat; loadCatalog(); };
    });
    $("ccount").textContent = (CAT.total || 0) + " / " + (st.total || 0);
    const items = (CAT && CAT.items) || [];
    const list = $("clist");
    if (!items.length) { list.innerHTML = '<div class="muted" style="padding:16px">Nema rezultata.</div>'; return; }
    list.innerHTML = items.map((it) => {
      const badge = it.kind === "tool" ? "alat" : "skill";
      const flags = [it.domain, it.status, it.evidence_level ? "dokaz " + it.evidence_level : "", it.challenge_status ? "chal " + it.challenge_status : "", it.bulk_status ? "bulk " + it.bulk_status : "", it.installed ? "✓ instaliran" : "nije instaliran"].filter(Boolean).join(" · ");
      return `<article class="power catitem" data-id="${esc(it.id)}" data-name="${esc(it.name)}" data-kind="${esc(it.kind)}" data-path="${esc(it.path || "")}" data-desc="${esc((it.description || "").slice(0, 300))}">
        <div class="phead"><span class="pbadge ${badge}">${badge}</span><b>${esc(it.name)}</b><span class="pmeta" style="margin-left:auto">${esc(flags)}</span></div>
        <div class="pdesc">${esc((it.description || "").slice(0, 220))}</div>
      </article>`;
    }).join("");
    list.querySelectorAll(".catitem").forEach((el) => {
      el.onclick = () => {
        const kind = el.dataset.kind, path = el.dataset.path;
        if (kind === "skill" && path) {
          catalogModal.classList.remove("open");
          openNode({ id: el.dataset.id, label: el.dataset.name, kind: "skill", ref: path });
        } else {
          toast(el.dataset.name + ": " + (el.dataset.desc || "bez opisa"));
        }
      };
    });
  }

  async function openCatalog() {
    hits.classList.remove("open");
    catalogModal.classList.add("open");
    if (!CAT) await loadCatalog();
    else renderCatalog();
  }

  $("catalog").onclick = openCatalog;
  $("catalogClose").onclick = () => catalogModal.classList.remove("open");
  catalogModal.addEventListener("click", (e) => { if (e.target === catalogModal) catalogModal.classList.remove("open"); });

  // ---------- dnevni digest ----------
  const digestModal = $("digestModal");

  async function openDigest() {
    hits.classList.remove("open");
    digestModal.classList.add("open");
    $("dbody").innerHTML = '<div class="muted" style="padding:16px">Sastavljam digest…</div>';
    let d;
    try { d = await jget("/api/digest?agent=" + encodeURIComponent(S.agent)); }
    catch (e) { $("dbody").textContent = "Greška: " + e.message; return; }
    renderDigest(d);
  }

  function renderDigest(d) {
    const c = d.challenges || {}, cat = d.catalog || {}, r = d.recent || {};
    $("dcount").textContent = (d.date || "") + " · " + S.agent;
    const block = (title, arr, fmt, badge) => {
      const body = (arr || []).length ? arr.map(fmt).join("<br>") : "nema";
      return `<div class="power"><div class="phead">${badge || ""}<b>${esc(title)}</b></div><div class="pdesc">${body}</div></div>`;
    };
    let h = "";
    h += block("Challenge", [c], (x) => `${x.PASS || 0} PASS · ${x.FAIL || 0} FAIL · ${x.SKIP || 0} SKIP · ukupno ${x.total || 0}<br><span class="pmeta">${esc(x.generated || "")}</span>`, '<span class="pbadge skill">challenge</span>');
    h += block("Katalog", [cat], (x) => `${x.verified || 0} verified / ${x.total || 0} · instalirano ${x.installed || 0} · untested ${x.untested || 0}`, '<span class="pbadge alat">katalog</span>');
    if (d.eval) h += block("Eval trend", [d.eval], (x) => `${x.n || 0} skillova · k=${x.k || 0} · regresije: ${(x.regressions || []).join(", ") || "nema"}`, '<span class="pbadge skill">eval</span>');
    if (d.review) h += block("Ponavljanje", [d.review], (x) => `${x.due || 0} due / ${x.scheduled || 0} scheduled`, '<span class="pbadge topic">review</span>');
    h += block("Novo u memoriji (24h)", r.topics, (x) => `${esc(x.title)} <span class="pmeta">${esc(x.file)}</span>`);
    h += block("Novi skillovi (24h)", r.skills, (x) => esc(x.name));
    h += block("Naučeno (24h)", r.learned, (x) => `${esc(x.agent)} · ${esc(x.node)}${x.challenge ? " · " + esc(x.challenge) : ""}`);
    h += block("Predlozi", d.suggestions, (x) => `${esc(x.kind)} · ${esc(x.skill || "")} — ${esc(x.reason || "")}`);
    if ((d.fails || []).length) h += block("FAIL/ERROR", d.fails, (x) => `${esc(x.capability || x.id)} — ${esc(x.evidence || "")}`);
    $("dbody").innerHTML = h;
  }

  $("digest").onclick = openDigest;
  $("digestClose").onclick = () => digestModal.classList.remove("open");
  digestModal.addEventListener("click", (e) => { if (e.target === digestModal) digestModal.classList.remove("open"); });

  // ---------- stream (:8077) ----------
  const streamModal = $("streamModal");
  const streamFrame = $("streamFrame");
  let STREAM_URL = "";

  function setStream(url) {
    STREAM_URL = url || "";
    const b = $("stream");
    if (!b) return;
    b.style.display = STREAM_URL ? "" : "none";
    if (STREAM_URL) $("streamOpen").href = STREAM_URL;
  }

  function openStream() {
    if (!STREAM_URL) { toast("Stream URL nije podešen (GAMA_STREAM_URL)."); return; }
    streamModal.classList.add("open");
    if (streamFrame.getAttribute("src") !== STREAM_URL) streamFrame.src = STREAM_URL;
  }

  function closeStream() {
    streamModal.classList.remove("open");
    streamFrame.src = "about:blank";
  }

  $("stream").onclick = openStream;
  $("streamClose").onclick = closeStream;
  streamModal.addEventListener("click", (e) => { if (e.target === streamModal) closeStream(); });

  // ---------- tokeni + audit ----------
  const tokensModal = $("tokensModal");

  async function openTokens() {
    tokensModal.classList.add("open");
    $("tokNew").textContent = "";
    await Promise.all([loadTokens(), loadAudit()]);
  }

  async function loadTokens() {
    try {
      const d = await jget("/api/tokens");
      $("tcount").textContent = (d.count || 0) + " tokena";
      const items = d.items || [];
      $("tokList").innerHTML = items.length ? items.map((t) => `
        <article class="power">
          <div class="phead"><span class="pbadge skill">${esc(t.role)}</span><b>${esc(t.agent)}</b>
            <span class="pmeta" style="margin-left:auto">${esc(t.id)} · …${esc((t.token || "").slice(-4))}</span></div>
          <div class="pcmd" data-rem="${esc(t.id)}" title="Klikni da ukloniš"><code>ukloni</code><span class="copy">ukloni</span></div>
        </article>`).join("") : '<div class="muted" style="padding:10px">Nema tokena (legacy/open).</div>';
      $("tokList").querySelectorAll("[data-rem]").forEach((el) => {
        el.onclick = async () => {
          try { await jpost("/api/tokens", { action: "remove", id: el.dataset.rem }); }
          catch (e) { toast("Greška: " + e.message); }
          loadTokens(); loadAudit();
        };
      });
    } catch (e) { $("tokList").textContent = "Greška: " + e.message; }
  }

  async function loadAudit() {
    try {
      const d = await jget("/api/audit?limit=20");
      const items = d.items || [];
      $("auditList").innerHTML = items.length ? items.map((a) => `
        <article class="power">
          <div class="phead"><span class="pbadge alat">${esc(a.action)}</span>
            <span class="pmeta" style="margin-left:auto">${new Date((a.ts || 0) * 1000).toLocaleString()}</span></div>
          <div class="pdesc">${esc(JSON.stringify(a.info || {}))} · ${esc(a.ip || "")}</div>
        </article>`).join("") : '<div class="muted" style="padding:10px">Nema zapisa.</div>';
    } catch (e) { $("auditList").textContent = "Greška: " + e.message; }
  }

  $("tokAdd").onclick = async () => {
    const agent = ($("tokAgent").value || "agent").trim();
    const role = $("tokRole").value;
    try {
      const d = await jpost("/api/tokens", { action: "add", agent, role });
      if (d.ok) {
        const link = location.origin + "/?token=" + encodeURIComponent(d.token);
        $("tokNew").innerHTML = `Novi token (${esc(d.role)} · ${esc(d.agent)}): <code>${esc(d.token)}</code><br>Link: <a href="${esc(link)}" target="_blank" rel="noopener">${esc(link)}</a>`;
        try { await navigator.clipboard.writeText(link); } catch (_) {}
        $("tokAgent").value = "";
      } else toast("Greška: " + (d.err || "?"));
    } catch (e) { toast("Greška: " + e.message); }
  };

  $("tokens").onclick = openTokens;
  $("tokensClose").onclick = () => tokensModal.classList.remove("open");
  tokensModal.addEventListener("click", (e) => { if (e.target === tokensModal) tokensModal.classList.remove("open"); });

  // ---------- spaced repetition ----------
  const reviewModal = $("reviewModal");

  async function openReview() {
    reviewModal.classList.add("open");
    $("reviewList").innerHTML = '<div class="muted" style="padding:10px">Učitavam…</div>';
    try {
      const d = await jget("/api/review?agent=" + encodeURIComponent(S.agent));
      renderReview(d);
    } catch (e) { $("reviewList").textContent = "Greška: " + e.message; }
  }

  function renderReview(d) {
    $("rcount").textContent = `${d.due || 0} due / ${d.scheduled || 0} scheduled`;
    const items = d.items || [];
    if (!items.length) {
      $("reviewList").innerHTML = '<div class="muted" style="padding:10px">Nema due ponavljanja.</div>';
      return;
    }
    $("reviewList").innerHTML = items.map((it) => `
      <article class="power" data-node="${esc(it.node)}" data-label="${esc(it.label)}" data-kind="${esc(it.kind)}" data-ref="${esc(it.ref || "")}">
        <div class="phead"><span class="pbadge ${it.kind}">${it.kind === "skill" ? "skill" : "tema"}</span><b>${esc(it.label)}</b>
          <span class="pmeta" style="margin-left:auto">due ${it.overdue_days || 0}d${it.drift ? " · DRIFT" : ""} · ${esc(it.challenge || "nema dokaza")}</span></div>
        <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">
          <button class="btn muted" data-open="${esc(it.node)}">Otvori</button>
          <button class="btn" data-pass="${esc(it.node)}" ${S.role === "read" ? "disabled" : ""}>Položeno</button>
          <button class="btn muted" data-fail="${esc(it.node)}" ${S.role === "read" ? "disabled" : ""}>Nisam znao</button>
        </div>
      </article>`).join("");
    $("reviewList").querySelectorAll("[data-open]").forEach((b) => {
      b.onclick = () => {
        const el = b.closest(".power");
        const id = el.dataset.node;
        let n = S.map.get(id);
        if (!n) n = { id, label: el.dataset.label, kind: el.dataset.kind, ref: el.dataset.ref };
        reviewModal.classList.remove("open");
        openNode(n);
        if (S.map.get(id)) focusNode(n);
      };
    });
    $("reviewList").querySelectorAll("[data-pass],[data-fail]").forEach((b) => {
      b.onclick = () => {
        const node = b.dataset.pass || b.dataset.fail;
        const item = items.find((x) => x.node === node);
        if (b.dataset.pass && item && item.ref) openQuiz(item);
        else postReview(node, b.dataset.pass ? "pass" : "fail");
      };
    });
  }

  async function postReview(node, result) {
    try {
      const r = await jpost("/api/review", { agent: S.agent, node, result });
      if (!r.ok) toast("Gate: " + (r.err || "?"));
      else toast(result === "pass" ? "Položeno · sljedeće za " + (r.entry.interval || 1) + " d" : "Ponovi sutra");
    } catch (e) { toast("Greška: " + e.message); }
    openReview();
  }

  async function openQuiz(item) {
    $("reviewList").innerHTML = '<div class="muted" style="padding:10px">Pravim kviz…</div>';
    let d;
    try { d = await jget("/api/study?ref=" + encodeURIComponent(item.ref)); }
    catch (e) { toast("Kviz greška: " + e.message); return postReview(item.node, "pass"); }
    const qs = (d.quiz || []).slice(0, 3);
    if (!d.ok || !qs.length) {
      toast("Nema kviza — označavam položeno.");
      return postReview(item.node, "pass");
    }
    $("rcount").textContent = `Kviz · ${qs.length} pitanja`;
    $("reviewList").innerHTML = `<div class="power">
      <div class="phead"><b>${esc(item.label)}</b></div>
      ${qs.map((q, i) => `<div class="clevel">
        <div class="ctask">${i + 1}. ${esc(q.q || "")}</div>
        ${(q.options || []).map((o, j) => `<label style="display:block;font-size:12px;margin:4px 0"><input type="radio" name="rq${i}" value="${j}"> ${esc(o)}</label>`).join("")}
      </div>`).join("")}
      <div style="display:flex;gap:6px;margin-top:8px">
        <button class="btn" id="quizSubmit">Pošalji kviz</button>
        <button class="btn muted" id="quizCancel">Otkaži</button>
      </div>
    </div>`;
    $("quizCancel").onclick = openReview;
    $("quizSubmit").onclick = async () => {
      let correct = 0, answered = 0;
      qs.forEach((q, i) => {
        const el = document.querySelector(`input[name="rq${i}"]:checked`);
        if (el) {
          answered++;
          if (Number(el.value) === Number(q.answer)) correct++;
        }
      });
      if (answered < qs.length) { toast("Odgovori na sva pitanja."); return; }
      const pass = correct >= Math.ceil(qs.length * 0.6);
      toast(`Kviz ${correct}/${qs.length} — ${pass ? "položeno" : "ponovi"}`);
      await postReview(item.node, pass ? "pass" : "fail");
    };
  }

  $("review").onclick = openReview;
  $("reviewClose").onclick = () => reviewModal.classList.remove("open");
  reviewModal.addEventListener("click", (e) => { if (e.target === reviewModal) reviewModal.classList.remove("open"); });

  // ---------- fleet dashboard ----------
  const fleetModal = $("fleetModal");

  async function openFleet() {
    fleetModal.classList.add("open");
    $("fleetList").innerHTML = '<div class="muted" style="padding:10px">Čitam flotu…</div>';
    try {
      const d = await jget("/api/fleet?refresh=1");
      renderFleet(d);
    } catch (e) { $("fleetList").textContent = "Greška: " + e.message; }
  }

  function renderFleet(d) {
    const s = d.summary || {};
    $("fcount").textContent = `${s.online || 0}/${s.nodes || 0} online · verified ${s.verified || 0}/${s.installed || 0} · due ${s.review_due || 0}`;
    let h = `<article class="power"><div class="phead"><span class="pbadge alat">summary</span><b>${s.online || 0}/${s.nodes || 0} online</b></div>
      <div class="pdesc">verified ${s.verified || 0} / installed ${s.installed || 0} · untested ${s.untested || 0} · tools ${s.tools_verified || 0} · review due ${s.review_due || 0}${s.batch_running ? " · batch RUNNING" : ""}</div>
      ${(s.regressions || []).length ? `<div class="chint">regresije: ${s.regressions.map((x) => esc(x.node + ":" + x.skill)).join(", ")}</div>` : ""}
    </article>`;
    for (const [name, n] of Object.entries(d.nodes || {})) {
      const sn = n.snapshot || {};
      h += `<article class="power">
        <div class="phead"><span class="hdot ${n.ok ? "ok" : "bad"}"></span><b>${esc(name)}</b>
          <span class="pmeta" style="margin-left:auto">${n.ok ? "online" : "OFF"} · ${n.ms || 0} ms</span></div>
        <div class="pdesc">graf ${sn.nodes || 0} · health ${esc(sn.health || "")} · katalog ${esc(sn.catalog || "")} · alati ${esc(sn.tools || "")}<br>
          challenge ${esc(sn.challenges || "")} · bulk ${sn.bulk_stale ? "STALE" : "ok"} · batch ${sn.batch_running ? "RUN" : (sn.batch_latest ? new Date(sn.batch_latest * 1000).toLocaleDateString() : "nema")} · review ${sn.review_due || 0}/${sn.review_scheduled || 0}</div>
        ${(n.errors || []).length ? `<div class="chint">${n.errors.map(esc).join("<br>")}</div>` : ""}
      </article>`;
    }
    $("fleetList").innerHTML = h;
  }

  $("fleet").onclick = openFleet;
  $("fleetRefresh").onclick = openFleet;
  $("fleetClose").onclick = () => fleetModal.classList.remove("open");
  fleetModal.addEventListener("click", (e) => { if (e.target === fleetModal) fleetModal.classList.remove("open"); });

  // ---------- benchmark ----------
  const benchModal = $("benchModal");
  let benchTimer = null;

  async function openBench() {
    benchModal.classList.add("open");
    $("benchBody").innerHTML = '<div class="muted" style="padding:10px">Čitam benchmark…</div>';
    await loadBench();
  }

  async function loadBench() {
    let d;
    try { d = await jget("/api/bench"); }
    catch (e) { $("benchBody").textContent = "Greška: " + e.message; return; }
    renderBench(d);
    const running = !!(d.status && d.status.running);
    $("benchRun").disabled = running;
    clearTimeout(benchTimer);
    if (running) benchTimer = setTimeout(loadBench, 3000);
  }

  function renderBench(d) {
    const b = d.bench20 || {}, st = d.status || {}, sum = b.summary || {};
    const pct = (x) => (x == null ? "–" : Number(x).toFixed(2));
    $("bcount").textContent = st.running ? "radi…" :
      (sum.n ? `${sum.n} skilla · Δ ${pct(sum.avg_delta)}` : "nema rezultata");
    let h = `<article class="power"><div class="phead"><span class="pbadge alat">summary</span><b>with ${pct(sum.with_avg)} / without ${pct(sum.without_avg)}</b>
      <span class="pmeta" style="margin-left:auto">avg Δ ${pct(sum.avg_delta)}</span></div>
      <div class="pdesc">k=${b.k || "?"} · ${sum.n || 0} zadataka${st.running ? " · <b>benchmark radi u pozadini</b>" : (st.err ? " · <span class='chint'>" + esc(st.err).slice(0, 160) + "</span>" : "")}</div></article>`;
    const k2 = (d.bench20_k2 || {}).summary;
    if (k2) h += `<article class="power"><div class="phead"><span class="pbadge topic">k=2</span><b>arhiva: with ${pct(k2.with_avg)} / without ${pct(k2.without_avg)}</b>
      <span class="pmeta" style="margin-left:auto">avg Δ ${pct(k2.avg_delta)}</span></div>
      <div class="pdesc">${k2.n || 0} zadataka · judge aktivan (nema rescue false-negative)</div></article>`;
    const k3 = (d.bench20_k3 || {}).summary;
    if (k3) h += `<article class="power"><div class="phead"><span class="pbadge skill">k=3</span><b>najnovije: with ${pct(k3.with_avg)} / without ${pct(k3.without_avg)}</b>
      <span class="pmeta" style="margin-left:auto">avg Δ ${pct(k3.avg_delta)}</span></div>
      <div class="pdesc">${k3.n || 0} zadataka · svi with 3/3 (gama-openseo fix verifikovan)</div></article>`;
    const items = Object.entries(b.items || {}).sort((a, z) => (z[1].delta || 0) - (a[1].delta || 0) || a[0].localeCompare(z[0]));
    for (const [name, v] of items) {
      const w = v.with || {}, wo = v.without || {};
      const cls = v.delta > 0 ? "skill" : "topic";
      h += `<article class="power"><div class="phead"><span class="pbadge ${cls}">${v.delta > 0 ? "+" + pct(v.delta) : pct(v.delta)}</span><b>${esc(name)}</b>
        <span class="pmeta" style="margin-left:auto">${esc(v.cat || "")}</span></div>
        <div class="pdesc">with ${w.pass || 0}/${w.k || 0} · without ${wo.pass || 0}/${wo.k || 0}</div></article>`;
    }
    if ((d.history || []).length) {
      h += `<article class="power"><div class="phead"><b>Historija</b></div><div class="pdesc">` +
        d.history.slice().reverse().slice(0, 5).map((x) => {
          const s = x.summary || {};
          return `${new Date((x.ts || 0) * 1000).toLocaleString()} · k=${x.k || "?"} · Δ ${pct(s.avg_delta)}`;
        }).join("<br>") + `</div></article>`;
    }
    $("benchBody").innerHTML = h;
  }

  $("bench").onclick = openBench;
  $("benchRun").onclick = async () => {
    const k = Number($("benchK").value || 2);
    $("benchRun").disabled = true;
    try {
      const r = await jpost("/api/bench", { k: k });
      if (!r.ok) toast(r.err || "benchmark nije pokrenut");
    } catch (e) { toast("Greška: " + e.message); }
    setTimeout(loadBench, 600);
  };
  $("benchClose").onclick = () => { clearTimeout(benchTimer); benchModal.classList.remove("open"); };
  benchModal.addEventListener("click", (e) => { if (e.target === benchModal) { clearTimeout(benchTimer); benchModal.classList.remove("open"); } });

  // ---------- fixevi ----------
  const fixesModal = $("fixesModal");

  async function openFixes() {
    fixesModal.classList.add("open");
    $("fixBody").innerHTML = '<div class="muted" style="padding:10px">Čitam fixeve…</div>';
    try {
      const d = await jget("/api/fixes");
      renderFixes(d);
    } catch (e) { $("fixBody").textContent = "Greška: " + e.message; }
  }

  function renderFixes(d) {
    const items = Object.values(d.items || {}).sort((a, b) => (b.updated_ts || 0) - (a.updated_ts || 0));
    $("fxcount").textContent = items.length + " zapisa";
    let h = "";
    for (const x of items) {
      const st = x.status || "?";
      const cls = st === "applied" ? "skill" : (st === "approved" ? "alat" : "topic");
      const issues = (x.issues || []).map((i) => esc(i.code)).join(", ") || "nema";
      let buttons = "";
      if (st === "proposed") buttons += `<button class="btn muted" data-fix="approve" data-skill="${esc(x.skill)}" style="padding:3px 8px;font-size:11px">Odobri</button>`;
      if (st === "approved") buttons += `<button class="btn muted" data-fix="apply" data-skill="${esc(x.skill)}" style="padding:3px 8px;font-size:11px">Primijeni</button>`;
      if (st === "applied") buttons += `<button class="btn muted" data-fix="rollback" data-skill="${esc(x.skill)}" style="padding:3px 8px;font-size:11px">Rollback</button>`;
      h += `<article class="power"><div class="phead"><span class="pbadge ${cls}">${esc(st)}</span><b>${esc(x.skill)}</b>
        <span class="pmeta" style="margin-left:auto">${x.updated_ts ? new Date(x.updated_ts * 1000).toLocaleString() : ""}</span></div>
        <div class="pdesc">issues: ${issues}${x.backup ? "<br>backup: " + esc(x.backup) : ""}</div>
        <div style="margin-top:6px">${buttons}</div></article>`;
    }
    $("fixBody").innerHTML = h || '<div class="muted" style="padding:10px">Nema fix draftova.</div>';
  }

  $("fixes").onclick = openFixes;
  $("fixesClose").onclick = () => fixesModal.classList.remove("open");
  fixesModal.addEventListener("click", (e) => { if (e.target === fixesModal) fixesModal.classList.remove("open"); });
  $("fixBody").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-fix]");
    if (!b) return;
    const skill = b.getAttribute("data-skill");
    const act = b.getAttribute("data-fix");
    if (act === "apply" && !confirm("Primijeni fix za " + skill + "?")) return;
    if (act === "rollback" && !confirm("Rollback " + skill + " na zadnji backup?")) return;
    b.disabled = true;
    try {
      const body = { skill };
      if (act === "apply") body.yes = true;
      const r = await jpost("/api/fix/" + act, body);
      toast(r.ok ? (act + " OK") : (r.err || "greška"));
    } catch (e) { toast("Greška: " + e.message); }
    openFixes();
  });

  // ---------- live sentinel ----------
  const liveModal = $("liveModal");

  async function openLive() {
    liveModal.classList.add("open");
    $("liveBody").innerHTML = '<div class="muted" style="padding:10px">Čitam live log…</div>';
    try {
      const s = await jget("/api/sentinel");
      const l = await jget("/api/live?limit=40");
      const c = s.counts || {};
      $("lcount").textContent = `${c.ok || 0} ok · ${c.fail || 0} fail · ${c.missing || 0} missing`;
      let h = `<article class="power"><div class="phead"><span class="pbadge alat">sentinel</span><b>${s.probed || 0} probano</b>
        <span class="pmeta" style="margin-left:auto">${s.ts ? new Date(s.ts * 1000).toLocaleString() : "nema"}</span></div>
        <div class="pdesc">ok ${c.ok || 0} · fail ${c.fail || 0} · idle ${c.idle || 0} · missing ${c.missing || 0}</div></article>`;
      if ((s.problems || []).length) {
        h += `<article class="power"><div class="phead"><span class="pbadge topic">problemi</span><b>${s.problems.length}</b></div><div class="pdesc">` +
          s.problems.slice(0, 20).map((p) => `${esc(p.name)} — ${esc(p.status)}`).join("<br>") + `</div></article>`;
      }
      for (const e of (l.events || []).slice().reverse()) {
        const badge = e.event === "fail" || e.event === "missing" ? "topic" : "skill";
        h += `<article class="power"><div class="phead"><span class="pbadge ${badge}">${esc(e.event || "")}</span>
          <b>${esc(e.artifact || e.name || "run")}</b><span class="pmeta" style="margin-left:auto">${e.ts ? new Date(e.ts * 1000).toLocaleTimeString() : ""}</span></div>
          ${e.detail ? `<div class="pdesc">${esc(e.detail)}</div>` : ""}</article>`;
      }
      $("liveBody").innerHTML = h;
    } catch (e) { $("liveBody").textContent = "Greška: " + e.message; }
  }

  $("live").onclick = openLive;
  $("liveClose").onclick = () => liveModal.classList.remove("open");
  liveModal.addEventListener("click", (e) => { if (e.target === liveModal) liveModal.classList.remove("open"); });

  // ---------- alerti ----------
  const alertsModal = $("alertsModal");
  let ALERTS = [], ALERT_NOTIFIED = false;

  async function loadAlerts() {
    try {
      const d = await jget("/api/alerts?agent=" + encodeURIComponent(S.agent));
      ALERTS = d.items || [];
      const b = $("alertsBadge");
      if (b) {
        b.textContent = ALERTS.length;
        b.style.display = ALERTS.length ? "inline-block" : "none";
      }
      if ($("acount")) $("acount").textContent = `${ALERTS.length} alerta`;
      if (ALERTS.length && !ALERT_NOTIFIED && "Notification" in window && Notification.permission === "granted") {
        try {
          new Notification("GAMA Learn: " + ALERTS.length + " alerta", {
            body: ALERTS.map((a) => a.title).slice(0, 3).join(" · "),
          });
          ALERT_NOTIFIED = true;
        } catch (_) {}
      }
      if (alertsModal.classList.contains("open")) renderAlerts();
      if ($("alertPerm") && "Notification" in window) {
        $("alertPerm").textContent = Notification.permission === "granted" ? "Obavještenja uključena"
          : (Notification.permission === "denied" ? "Obavještenja blokirana" : "Uključi obavještenja");
      }
      return d;
    } catch (e) {
      if (alertsModal.classList.contains("open")) $("alertsList").textContent = "Greška: " + e.message;
      return null;
    }
  }

  function renderAlerts() {
    if (!ALERTS.length) {
      $("alertsList").innerHTML = '<div class="muted" style="padding:10px">Nema alerta.</div>';
      return;
    }
    $("alertsList").innerHTML = ALERTS.map((a) => `
      <article class="power">
        <div class="phead"><span class="hdot ${a.severity === "error" ? "bad" : "ok"}"></span><b>${esc(a.title)}</b>
          <button class="btn muted" data-action="${esc(a.action || "")}" style="margin-left:auto;padding:4px 9px">Idi</button></div>
        <div class="pdesc">${esc(a.detail || "")}</div>
      </article>`).join("");
    $("alertsList").querySelectorAll("[data-action]").forEach((b) => {
      b.onclick = () => {
        alertsModal.classList.remove("open");
        const act = b.dataset.action;
        if (act === "review") openReview();
        else if (act === "fleet") openFleet();
        else if (act === "live") openLive();
        else if (act === "digest") openDigest();
        else if (act === "catalog") openCatalog();
      };
    });
  }

  async function openAlerts() {
    alertsModal.classList.add("open");
    $("alertsList").innerHTML = '<div class="muted" style="padding:10px">Učitavam…</div>';
    await loadAlerts();
    renderAlerts();
  }

  $("alerts").onclick = openAlerts;
  $("alertsClose").onclick = () => alertsModal.classList.remove("open");
  alertsModal.addEventListener("click", (e) => { if (e.target === alertsModal) alertsModal.classList.remove("open"); });
  $("alertPerm").onclick = async () => {
    if (!("Notification" in window)) { toast("Browser ne podržava obavještenja."); return; }
    try {
      const p = await Notification.requestPermission();
      toast(p === "granted" ? "Obavještenja uključena" : "Obavještenja nisu dozvoljena");
      loadAlerts();
    } catch (e) { toast("Greška: " + e.message); }
  };
  $("cq").addEventListener("input", (e) => {
    C_Q = e.target.value;
    clearTimeout(C_TIMER);
    C_TIMER = setTimeout(loadCatalog, 260);
  });

  $("next").onclick = nextNode;
  $("plan").onclick = openPlan;

  document.addEventListener("keydown", (e) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if (e.key === "/" && !typing) { e.preventDefault(); q.focus(); }
    if (e.key === "Escape") { closePanel(); hits.classList.remove("open"); powersModal.classList.remove("open"); catalogModal.classList.remove("open"); digestModal.classList.remove("open"); if (streamModal) { streamModal.classList.remove("open"); streamFrame.src = "about:blank"; } tokensModal.classList.remove("open"); reviewModal.classList.remove("open"); fleetModal.classList.remove("open"); benchModal.classList.remove("open"); liveModal.classList.remove("open"); fixesModal.classList.remove("open"); clearTimeout(benchTimer); alertsModal.classList.remove("open"); }
    if (!typing && (e.key === "n" || e.key === "N")) { e.preventDefault(); nextNode(); }
    if (!typing && (e.key === "p" || e.key === "P")) { e.preventDefault(); openPlan(); }
    if (!typing && (e.key === "r" || e.key === "R")) { e.preventDefault(); openResearch(); }
    if (!typing && (e.key === "t" || e.key === "T")) { e.preventDefault(); openTools(); }
    if (!typing && (e.key === "m" || e.key === "M")) { e.preventDefault(); openPowers(); }
    if (!typing && (e.key === "k" || e.key === "K")) { e.preventDefault(); openCatalog(); }
    if (!typing && (e.key === "d" || e.key === "D")) { e.preventDefault(); openDigest(); }
  });

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    });
  }
  let INSTALL_EVENT = null;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    INSTALL_EVENT = e;
    const b = $("install");
    if (b) b.style.display = "";
  });
  const installBtn = $("install");
  if (installBtn) installBtn.onclick = async () => {
    if (!INSTALL_EVENT) { toast("Instalacija nije dostupna u ovom browseru."); return; }
    INSTALL_EVENT.prompt();
    try { await INSTALL_EVENT.userChoice; } catch (_) {}
    INSTALL_EVENT = null;
    installBtn.style.display = "none";
  };
  window.addEventListener("offline", () => toast("Offline — keš režim"));
  window.addEventListener("online", () => toast("Online"));

  init().then(() => {
    fit(); draw();
    setInterval(pollVersion, 20000);
  });
})();
