"""Live training dashboard — zero extra dependencies (stdlib only).

Serves one self-contained dark HTML page that polls the run's status JSON
(written atomically by crpg_rle.train.observer.StatusWriter) about once a
second, plus the run CSV for the loss sparkline.

Usage:
    python tools/dashboard.py --dir runs/<run> [--port 8008] [--host 127.0.0.1]

Routes:
    /             the dashboard page (inline CSS/JS, CSP-safe, no CDNs)
    /status.json  <dir>/live_status.json
    /csv          the run CSV (path taken from status.json's "csv" field,
                  falling back to the newest *.csv inside --dir)
"""
from __future__ import annotations

import argparse
import http.server
import json
from pathlib import Path
from urllib.parse import urlparse

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>crpg-rle live run</title>
<style>
:root{
  --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7;
  --muted:#898781; --grid:#2c2c2a; --baseline:#383835;
  --border:rgba(255,255,255,0.10);
  --s1:#3987e5; --s2:#199e70; --s3:#c98500; --s4:#008300;
  --s5:#9085e9; --s6:#e66767; --s7:#d55181; --s8:#d95926;
  --good:#0ca30c; --warn:#fab219; --serious:#ec835a; --crit:#d03b3b;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--page);color:var(--ink);
  font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;padding:16px}
h1{font-size:16px;font-weight:600}
header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:14px}
header .sub{color:var(--muted);font-size:12px}
#age{font-size:12px;color:var(--ink2)}
#age.stale{color:var(--crit);font-weight:600}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));
  gap:8px;margin-bottom:12px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:8px;
  padding:8px 12px}
.tile .k{font-size:11px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.04em}
.tile .v{font-size:20px;font-weight:600;margin-top:2px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.tile .v small{font-size:12px;color:var(--ink2);font-weight:400}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:8px;
  padding:12px;min-width:0}
.card h2{font-size:12px;color:var(--ink2);font-weight:600;text-transform:uppercase;
  letter-spacing:.05em;margin-bottom:10px;display:flex;gap:8px;align-items:center;
  justify-content:space-between}
.card.wide{grid-column:1/-1}
select{background:var(--page);color:var(--ink);border:1px solid var(--border);
  border-radius:5px;padding:2px 6px;font:12px system-ui}
#spark{width:100%;height:150px;display:block;cursor:crosshair}
#sparktip{position:fixed;pointer-events:none;background:var(--page);color:var(--ink);
  border:1px solid var(--border);border-radius:5px;padding:3px 7px;font-size:12px;
  display:none;z-index:9;font-variant-numeric:tabular-nums}
.bar-row{display:grid;grid-template-columns:110px 1fr 70px;gap:8px;
  align-items:center;margin:4px 0;font-size:12px}
.bar-row .name{color:var(--ink2);overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.bar-row .val{text-align:right;color:var(--ink);
  font-variant-numeric:tabular-nums}
.track{position:relative;height:12px;background:var(--page);border-radius:4px;
  overflow:hidden}
.track .mid{position:absolute;left:50%;top:0;bottom:0;width:1px;
  background:var(--baseline)}
.track .fill{position:absolute;top:1px;bottom:1px;border-radius:3px}
table.kv{width:100%;border-collapse:collapse;font-size:12px}
table.kv td{padding:3px 6px;border-bottom:1px solid var(--grid)}
table.kv td:first-child{color:var(--ink2)}
table.kv td:last-child{text-align:right;font-variant-numeric:tabular-nums}
ul.feed{list-style:none;max-height:230px;overflow-y:auto;font-size:12px}
ul.feed li{padding:4px 2px;border-bottom:1px solid var(--grid);display:flex;
  gap:8px;align-items:baseline}
ul.feed .step{color:var(--muted);min-width:52px;
  font-variant-numeric:tabular-nums}
.badge{display:inline-block;padding:0 6px;border-radius:8px;font-size:11px;
  font-weight:600;color:var(--page)}
ul.feed .body{color:var(--ink2);word-break:break-word}
.hp-row{display:grid;grid-template-columns:70px 1fr 80px;gap:8px;
  align-items:center;margin:5px 0;font-size:12px}
.hp-row .who{color:var(--ink2)}
.hp-row .num{text-align:right;font-variant-numeric:tabular-nums}
.empty{color:var(--muted);font-size:12px}
footer{color:var(--muted);font-size:11px;margin-top:14px}
</style>
</head>
<body>
<header>
  <h1>crpg-rle live run</h1>
  <span class="sub" id="rundir"></span>
  <span id="age">waiting for live_status.json…</span>
</header>

<div class="tiles">
  <div class="tile"><div class="k">Mode</div><div class="v" id="mode">–</div></div>
  <div class="tile"><div class="k">Update</div><div class="v" id="update">–</div></div>
  <div class="tile"><div class="k">Step</div><div class="v" id="step">–</div></div>
  <div class="tile"><div class="k">Episode</div><div class="v" id="episode">–</div></div>
  <div class="tile"><div class="k">Ep reward</div><div class="v" id="epreward">–</div></div>
  <div class="tile"><div class="k">Last ep</div><div class="v" id="lastep">–</div></div>
  <div class="tile"><div class="k">Target faction</div><div class="v" id="faction">–</div></div>
  <div class="tile"><div class="k">Interventions</div><div class="v" id="ivtotal">–</div></div>
</div>

<div class="grid">
  <div class="card wide">
    <h2><span>Loss history <span id="sparkinfo" style="color:var(--muted)"></span></span>
        <select id="metric"></select></h2>
    <canvas id="spark"></canvas>
    <div id="sparktip"></div>
  </div>
  <div class="card"><h2>Reward channels — this rollout</h2><div id="channels"></div></div>
  <div class="card"><h2>Last update — training metrics</h2>
    <table class="kv" id="train"></table></div>
  <div class="card"><h2>Action mix — this rollout</h2><div id="actions"></div></div>
  <div class="card"><h2>Party HP</h2><div id="party"></div></div>
  <div class="card"><h2>Recent game events</h2><ul class="feed" id="events"></ul></div>
  <div class="card"><h2>Recent interventions</h2><ul class="feed" id="ivs"></ul></div>
</div>
<footer>milestones: <span id="milestones">–</span></footer>

<script>
"use strict";
const $ = id => document.getElementById(id);
const SERIES = ["#3987e5","#199e70","#c98500","#008300","#9085e9","#e66767",
                "#d55181","#d95926"];
// Fixed hue order per entity: known channels pre-seeded, extras appended once,
// never cycled — beyond 8 entities the color folds to muted gray.
const slots = {};
["milestone","faction_favor","objective","explore","death","pause","offscreen",
 "recovery"].forEach((c,i)=>slots[c]=SERIES[i]);
function colorFor(name){
  if(!(name in slots)){
    const used = Object.keys(slots).length;
    slots[name] = used < SERIES.length ? SERIES[used] : "#898781";
  }
  return slots[name];
}
const fmt = v => (v==null||isNaN(v)) ? "–" :
  Math.abs(v)>=1000 ? v.toFixed(0) : Math.abs(v)>=10 ? v.toFixed(2) : v.toFixed(3);

// ------------------------------------------------------------------ status
let lastTs = null;
async function tickStatus(){
  try{
    const r = await fetch("/status.json", {cache:"no-store"});
    if(!r.ok) return;
    render(await r.json());
  }catch(e){/* trainer not up yet */}
}
function render(s){
  lastTs = s.ts;
  $("rundir").textContent = s.run_dir || "";
  $("mode").textContent = s.mode_name || (s.mode==null ? "–" : s.mode);
  $("update").textContent = s.update ?? "–";
  $("step").textContent = s.global_step ?? "–";
  $("episode").textContent = s.episode ?? "–";
  $("epreward").textContent = fmt(s.ep_reward);
  $("lastep").textContent = fmt(s.last_ep_reward);
  $("faction").textContent = s.target_faction || "–";
  $("ivtotal").textContent = s.intervention_total ?? 0;
  $("milestones").textContent =
    (s.milestones_fired && s.milestones_fired.length)
      ? s.milestones_fired.join(", ") : "none yet";
  renderChannels(s.rollout && s.rollout.channels || {});
  renderTrain(s.last_update || {}, s.rollout || {});
  renderActions(s.actions || {});
  renderParty(s.party);
  renderFeed($("events"), s.recent_events || [], evBadge, evBody);
  renderFeed($("ivs"), s.recent_interventions || [], ivBadge, ivBody);
}
function signedBar(name, v, maxAbs, color){
  const w = maxAbs > 0 ? Math.min(50, 50*Math.abs(v)/maxAbs) : 0;
  const side = v >= 0 ? "left:50%" : ("right:50%");
  return `<div class="bar-row"><span class="name">${name}</span>` +
    `<span class="track"><span class="mid"></span>` +
    `<span class="fill" style="${side};width:${w}%;background:${color}"></span></span>` +
    `<span class="val">${fmt(v)}</span></div>`;
}
function renderChannels(ch){
  const names = Object.keys(ch);
  if(!names.length){ $("channels").innerHTML =
    '<div class="empty">no reward yet this rollout</div>'; return; }
  const maxAbs = Math.max(...names.map(n=>Math.abs(ch[n])));
  names.sort((a,b)=>Math.abs(ch[b])-Math.abs(ch[a]));
  $("channels").innerHTML =
    names.map(n=>signedBar(n, ch[n], maxAbs, colorFor(n))).join("");
}
const TRAIN_KEYS = ["pg_loss","v_loss","entropy","approx_kl","clipfrac",
                    "ep_return","rollout_reward","n_ep","wall_s"];
function renderTrain(row, rollout){
  let html = `<tr><td>rollout steps (live)</td><td>${rollout.steps ?? 0}</td></tr>` +
    `<tr><td>rollout reward (live)</td><td>${fmt(rollout.reward)}</td></tr>`;
  for(const k of TRAIN_KEYS)
    if(k in row) html += `<tr><td>${k}</td><td>${
      typeof row[k]==="number" ? fmt(row[k]) : row[k]}</td></tr>`;
  $("train").innerHTML = html ||
    '<tr><td class="empty">no update finished yet</td><td></td></tr>';
}
function plainBar(name, v, max, color){
  const w = max>0 ? 100*v/max : 0;
  return `<div class="bar-row"><span class="name">${name}</span>` +
    `<span class="track"><span class="fill" style="left:0;width:${w}%;background:${color}"></span></span>` +
    `<span class="val">${v}</span></div>`;
}
function renderActions(a){
  const btns = a.buttons || {}, keys = a.keys || {};
  const order = ["none","left","right","double"];
  const bmax = Math.max(1, ...order.map(b=>btns[b]||0));
  let html = order.map((b,i)=>plainBar("btn "+b, btns[b]||0, bmax, SERIES[i])).join("");
  const top = Object.entries(keys).sort((x,y)=>y[1]-x[1]).slice(0,8);
  if(top.length){
    const kmax = top[0][1];
    html += '<div style="height:8px"></div>' +
      top.map(([k,v])=>plainBar(k, v, kmax, "#898781")).join("");
  }
  $("actions").innerHTML = html || '<div class="empty">no actions yet</div>';
}
function renderParty(party){
  if(!party || !party.length){
    $("party").innerHTML = '<div class="empty">no party data (proxy env or menu)</div>';
    return;
  }
  $("party").innerHTML = party.map((m,i)=>{
    const hp = +m.hp || 0, max = +m.max_hp || 0;
    const frac = max>0 ? hp/max : 0;
    const color = m.dead ? "var(--crit)" :
      frac > .5 ? "var(--good)" : frac > .25 ? "var(--warn)" : "var(--crit)";
    const label = m.dead ? "✝ dead" : `${hp.toFixed(0)}/${max.toFixed(0)}`;
    return `<div class="hp-row"><span class="who">${m.name || ("slot "+i)}</span>` +
      `<span class="track"><span class="fill" style="left:0;width:${
        Math.max(0,Math.min(100,100*frac))}%;background:${color}"></span></span>` +
      `<span class="num">${label}</span></div>`;
  }).join("");
}
function esc(s){ return String(s).replace(/[&<>"]/g,
  c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function evBadge(ev){
  const colors = {quest:"#3987e5", area:"#199e70", conversation:"#9085e9",
                  reputation:"#c98500", level_up:"#d55181"};
  return `<span class="badge" style="background:${
    colors[ev.type] || "#898781"}">${esc(ev.type || "event")}</span>`;
}
function evBody(ev){
  const rest = Object.entries(ev)
    .filter(([k])=>k!=="type" && k!=="step")
    .map(([k,v])=>`${esc(k)}=${esc(typeof v==="object"?JSON.stringify(v):v)}`);
  return rest.join("  ");
}
function ivBadge(iv){
  return `<span class="badge" style="background:var(--warn)">⚙ ${esc(iv.kind||"?")}</span>`;
}
function ivBody(iv){
  const d = iv.detail || {};
  const failed = d.ok === false;
  return `#${iv.seq ?? "?"} ${esc(JSON.stringify(d))}` +
    (failed ? ' <span style="color:var(--crit)">FAILED</span>' : "");
}
function renderFeed(el, items, badge, body){
  if(!items.length){ el.innerHTML = '<li class="empty">nothing yet</li>'; return; }
  el.innerHTML = items.slice().reverse().map(it =>
    `<li><span class="step">${it.step ?? ""}</span>${badge(it)}` +
    `<span class="body">${body(it)}</span></li>`).join("");
}
// staleness indicator
setInterval(()=>{
  if(lastTs == null) return;
  const age = Date.now()/1000 - lastTs;
  const el = $("age");
  el.textContent = "updated " + (age < 2 ? "just now" : age.toFixed(0)+"s ago");
  el.classList.toggle("stale", age > 15);
}, 1000);

// --------------------------------------------------------------- sparkline
let csvRows = [], csvCols = [], sparkHover = -1;
const NON_METRIC = new Set(["update","step","n_ep","wall_s"]);
async function tickCsv(){
  try{
    const r = await fetch("/csv", {cache:"no-store"});
    if(!r.ok) return;
    parseCsv(await r.text());
    drawSpark();
  }catch(e){}
}
function parseCsv(text){
  const lines = text.trim().split(/\r?\n/);
  if(lines.length < 2){ csvRows = []; return; }
  csvCols = lines[0].split(",");
  csvRows = lines.slice(1).map(l=>l.split(",").map(Number));
  const sel = $("metric");
  const numeric = csvCols.filter((c,i)=>!NON_METRIC.has(c) &&
    csvRows.some(r=>isFinite(r[i])));
  if(sel.options.length !== numeric.length){
    const cur = sel.value || "pg_loss";
    sel.innerHTML = numeric.map(c=>`<option${c===cur?" selected":""}>${c}</option>`).join("");
    if(!numeric.includes(cur) && numeric.length) sel.value =
      numeric.includes("pg_loss") ? "pg_loss" : numeric[0];
  }
}
function seriesData(){
  const col = csvCols.indexOf($("metric").value);
  if(col < 0) return [];
  const stepCol = csvCols.indexOf("step");
  return csvRows.map(r=>({x: stepCol>=0 ? r[stepCol] : 0, y: r[col]}))
    .filter(p=>isFinite(p.y)).slice(-200);   // scrolling window
}
function drawSpark(){
  const canvas = $("spark"), dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight;
  canvas.width = W*dpr; canvas.height = H*dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr,dpr); ctx.clearRect(0,0,W,H);
  const pts = seriesData();
  $("sparkinfo").textContent = pts.length ?
    `· last ${fmt(pts[pts.length-1].y)} · ${pts.length} updates` : "· waiting for CSV";
  if(pts.length < 2) return;
  const pad = {l:8,r:56,t:8,b:8};
  let lo = Math.min(...pts.map(p=>p.y)), hi = Math.max(...pts.map(p=>p.y));
  if(lo === hi){ lo -= 1; hi += 1; }
  const X = i => pad.l + (W-pad.l-pad.r) * i/(pts.length-1);
  const Y = v => pad.t + (H-pad.t-pad.b) * (1-(v-lo)/(hi-lo));
  // recessive grid: three hairlines + edge value labels
  ctx.strokeStyle = "#2c2c2a"; ctx.lineWidth = 1;
  ctx.fillStyle = "#898781"; ctx.font = "10px system-ui";
  ctx.textAlign = "left"; ctx.textBaseline = "middle";
  [lo,(lo+hi)/2,hi].forEach(v=>{
    ctx.beginPath(); ctx.moveTo(pad.l, Y(v)); ctx.lineTo(W-pad.r, Y(v)); ctx.stroke();
    ctx.fillText(fmt(v), W-pad.r+6, Y(v));
  });
  // the line (single series — the title + selector name it; no legend needed)
  ctx.strokeStyle = "#3987e5"; ctx.lineWidth = 2;
  ctx.lineJoin = "round"; ctx.lineCap = "round";
  ctx.beginPath();
  pts.forEach((p,i)=>{ i ? ctx.lineTo(X(i),Y(p.y)) : ctx.moveTo(X(i),Y(p.y)); });
  ctx.stroke();
  // hover crosshair + point
  if(sparkHover >= 0 && sparkHover < pts.length){
    const hx = X(sparkHover), hy = Y(pts[sparkHover].y);
    ctx.strokeStyle = "#383835";
    ctx.beginPath(); ctx.moveTo(hx,pad.t); ctx.lineTo(hx,H-pad.b); ctx.stroke();
    ctx.fillStyle = "#3987e5";
    ctx.beginPath(); ctx.arc(hx,hy,4,0,Math.PI*2); ctx.fill();
    ctx.strokeStyle = "#1a1a19"; ctx.lineWidth = 2; ctx.stroke();
  }
}
$("spark").addEventListener("mousemove", e=>{
  const pts = seriesData();
  if(pts.length < 2) return;
  const rect = e.target.getBoundingClientRect();
  const pad = {l:8,r:56};
  const frac = (e.clientX-rect.left-pad.l)/(rect.width-pad.l-pad.r);
  sparkHover = Math.max(0, Math.min(pts.length-1, Math.round(frac*(pts.length-1))));
  const tip = $("sparktip");
  tip.style.display = "block";
  tip.style.left = (e.clientX+12)+"px"; tip.style.top = (e.clientY-28)+"px";
  tip.textContent = `${$("metric").value} ${fmt(pts[sparkHover].y)} @ step ${pts[sparkHover].x}`;
  drawSpark();
});
$("spark").addEventListener("mouseleave", ()=>{
  sparkHover = -1; $("sparktip").style.display = "none"; drawSpark();
});
$("metric").addEventListener("change", drawSpark);
window.addEventListener("resize", drawSpark);

tickStatus(); tickCsv();
setInterval(tickStatus, 1000);
setInterval(tickCsv, 3000);
</script>
</body>
</html>
"""


def find_csv(run_dir: Path) -> Path | None:
    """The CSV the status writer recorded, else the newest CSV in the dir."""
    status = run_dir / "live_status.json"
    try:
        csv = json.loads(status.read_text(encoding="utf-8")).get("csv")
        if csv and Path(csv).is_file():
            return Path(csv)
    except (OSError, ValueError):
        pass
    candidates = sorted(run_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    run_dir: Path  # set by serve()

    def do_GET(self):  # noqa: N802 (stdlib naming)
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            body = PAGE.encode("utf-8")
            self._respond(200, "text/html; charset=utf-8", body)
        elif path == "/status.json":
            self._send_file(self.run_dir / "live_status.json", "application/json")
        elif path == "/csv":
            csv = find_csv(self.run_dir)
            if csv is None:
                self._respond(404, "text/plain", b"no csv yet")
            else:
                self._send_file(csv, "text/csv")
        else:
            self._respond(404, "text/plain", b"not found")

    def _send_file(self, path: Path, ctype: str) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self._respond(404, "text/plain", b"not written yet")
            return
        self._respond(200, ctype, body)

    def _respond(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # quiet: polling floods the console
        pass


def serve(run_dir: str | Path, host: str = "127.0.0.1", port: int = 8008):
    """Build the HTTP server (returned unstarted so tests can drive it)."""
    handler = type("Handler", (DashboardHandler,), {"run_dir": Path(run_dir)})
    return http.server.ThreadingHTTPServer((host, port), handler)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, help="run directory (holds live_status.json)")
    ap.add_argument("--port", type=int, default=8008)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    httpd = serve(args.dir, args.host, args.port)
    print(f"dashboard: http://{args.host}:{httpd.server_address[1]}/  "
          f"(watching {Path(args.dir).resolve()})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
