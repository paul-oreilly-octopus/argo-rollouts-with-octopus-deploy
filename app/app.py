#!/usr/bin/env python3
"""Colour demo for Argo Rollouts (stdlib only).

MODE=app        Runs in each Rollout pod. Starts with a random colour (or START_COLOUR),
                serves a page in that colour, and reports unhealthy on /api/health while
                its colour is FAIL_COLOUR, which makes the Argo Rollouts analysis fail.
MODE=dashboard  Lists colour-demo Rollouts and pods via the Kubernetes API, renders a
                square per pod, and proxies colour changes through to the pods.
"""
import html
import json
import os
import random
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from string import Template

PORT = int(os.environ.get("PORT", "8080"))
FAIL_COLOUR = os.environ.get("FAIL_COLOUR", "red").strip().lower()
PALETTE = {
    "blue": "#2563eb",
    "green": "#16a34a",
    "teal": "#0d9488",
    "yellow": "#facc15",
    "orange": "#f97316",
    "pink": "#db2777",
    "purple": "#7c3aed",
    "red": "#dc2626",
}
DARK_TEXT = {"yellow"}
PART_OF_KEY = "app.kubernetes.io/part-of"
PART_OF_VALUE = "colour-demo"
ROLLOUT_LABEL = "colour-demo/rollout"


def text_colour(colour):
    return "#111827" if colour in DARK_TEXT else "#ffffff"


def random_colour(exclude=None):
    return random.choice([c for c in PALETTE if c not in (FAIL_COLOUR, exclude)])


def format_age(seconds):
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, content_type="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def log_message(self, fmt, *args):
        pass  # health checks and polling would drown the log; events are printed explicitly


# ---------------------------------------------------------------- app mode

class AppState:
    def __init__(self):
        # START_COLOUR: a palette colour, "random-with-red" (may pick FAIL_COLOUR), or
        # "random-without-red" / "random" (never picks FAIL_COLOUR).
        start = os.environ.get("START_COLOUR", "random-without-red").strip().lower()
        if start in PALETTE:
            self.colour = start
        elif start == "random-with-red":
            self.colour = random.choice(list(PALETTE))
        else:
            self.colour = random_colour()
        self.started = time.time()
        self.lock = threading.Lock()


STATE = None


def app_info():
    colour = STATE.colour
    return {
        "pod": os.environ.get("POD_NAME", socket.gethostname()),
        "namespace": os.environ.get("POD_NAMESPACE", ""),
        "node": os.environ.get("NODE_NAME", ""),
        "podIp": os.environ.get("POD_IP", ""),
        "container": os.environ.get("CONTAINER_NAME", ""),
        "image": os.environ.get("IMAGE", ""),
        "version": os.environ.get("APP_VERSION", "dev"),
        "rollout": os.environ.get("ROLLOUT_NAME", ""),
        "strategy": os.environ.get("STRATEGY", ""),
        "colour": colour,
        "colourHex": PALETTE[colour],
        "failColour": FAIL_COLOUR,
        "healthy": colour != FAIL_COLOUR,
        "startedAt": STATE.started,
    }


APP_PAGE = Template("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>$pod</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;background:$bg;color:$fg}
main{padding:24px;max-width:640px}
h1{font-size:56px;margin:0;text-transform:capitalize}
.status{font-weight:700;margin:0 0 16px}
dl{display:grid;grid-template-columns:auto 1fr;gap:4px 16px;font-family:ui-monospace,Consolas,monospace;font-size:14px}
dt{opacity:.75}
dd{margin:0;word-break:break-all}
.sw{display:flex;gap:8px;flex-wrap:wrap;margin-top:20px}
.sw button{width:36px;height:36px;border-radius:50%;border:3px solid rgba(255,255,255,.85);cursor:pointer}
</style></head>
<body><main>
<h1>$colour</h1>
<p class="status">$status</p>
<dl>
<dt>Pod</dt><dd>$pod</dd>
<dt>Container</dt><dd>$container</dd>
<dt>Image</dt><dd>$image</dd>
<dt>Version</dt><dd>$version</dd>
<dt>Rollout</dt><dd>$rollout ($strategy)</dd>
<dt>Namespace</dt><dd>$namespace</dd>
<dt>Node</dt><dd>$node / $podIp</dd>
<dt>Started</dt><dd>$started</dd>
</dl>
<div class="sw">$swatches</div>
</main>
<script>
function setColour(c) {
  fetch('api/colour', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({colour: c})})
    .then(function () { location.reload(); });
}
</script>
</body></html>
""")


def app_page():
    info = app_info()
    swatches = "".join(
        f'<button style="background:{hex_}" title="{name}" onclick="setColour(\'{name}\')"></button>'
        for name, hex_ in PALETTE.items()
    )
    values = {k: html.escape(str(v)) for k, v in info.items()}
    values.update(
        bg=PALETTE[info["colour"]],
        fg=text_colour(info["colour"]),
        status="Healthy" if info["healthy"] else f"UNHEALTHY: {FAIL_COLOUR} fails the rollout analysis",
        started=datetime.fromtimestamp(info["startedAt"], timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        swatches=swatches,
    )
    return APP_PAGE.substitute(values)


class AppHandler(Handler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/healthz":
            return self.send(200, "ok", "text/plain")
        if path == "/api/info":
            return self.send(200, app_info())
        if path == "/api/health":
            info = app_info()
            return self.send(200, {"healthy": info["healthy"], "colour": info["colour"], "pod": info["pod"]})
        if path == "/":
            return self.send(200, app_page(), "text/html; charset=utf-8")
        self.send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.split("?")[0] != "/api/colour":
            return self.send(404, {"error": "not found"})
        try:
            wanted = str(json.loads(self.read_body() or b"{}").get("colour", "random")).lower()
        except ValueError:
            return self.send(400, {"error": "invalid JSON"})
        with STATE.lock:
            old = STATE.colour
            if wanted == "random":
                STATE.colour = random_colour(exclude=old)
            elif wanted in PALETTE:
                STATE.colour = wanted
            else:
                return self.send(400, {"error": f"unknown colour {wanted}"})
        print(f"colour changed {old} -> {STATE.colour}", flush=True)
        self.send(200, app_info())


# ---------------------------------------------------------------- dashboard mode

SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"
POOL = ThreadPoolExecutor(max_workers=16)
POD_PATH = re.compile(r"^/pods/([a-z0-9][a-z0-9.-]*)/([a-z0-9][a-z0-9.-]*)(/.*)$")
ROLE_ORDER = {"stable": 0, "active": 0, "canary": 1, "preview": 1, "old": 2}
_ssl_context = None


def k8s(path):
    global _ssl_context
    if _ssl_context is None:
        _ssl_context = ssl.create_default_context(cafile=f"{SA_DIR}/ca.crt")
    with open(f"{SA_DIR}/token") as f:  # re-read each time: projected tokens rotate
        token = f.read().strip()
    host = os.environ["KUBERNETES_SERVICE_HOST"]
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    req = urllib.request.Request(f"https://{host}:{port}{path}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, context=_ssl_context, timeout=5) as r:
        return json.load(r)


def pod_http(ip, path, data=None, timeout=1.5):
    req = urllib.request.Request(
        f"http://{ip}:8080{path}",
        data=data,
        method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.headers.get("Content-Type", "application/octet-stream"), r.read()


def fetch_info(pod):
    ip = pod.get("status", {}).get("podIP")
    if not ip or pod["status"].get("phase") != "Running":
        return None
    try:
        return json.loads(pod_http(ip, "/api/info", timeout=1)[2])
    except (OSError, ValueError):
        return None


def pod_role(rollout, pod_hash):
    status = rollout.get("status", {})
    if "blueGreen" in rollout["spec"]["strategy"]:
        bg = status.get("blueGreen", {})
        if pod_hash == bg.get("activeSelector"):
            return "active"
        if pod_hash == bg.get("previewSelector"):
            return "preview"
        return "old"
    if pod_hash == status.get("stableRS"):
        return "stable"
    if pod_hash == status.get("currentPodHash"):
        return "canary"
    return "old"


def describe_step(step):
    if "setWeight" in step:
        return f"setWeight {step['setWeight']}%"
    if "pause" in step:
        duration = (step["pause"] or {}).get("duration")
        return f"pause {duration}" if duration else "pause (manual)"
    return next(iter(step), "?")


def analysis_summary(rollout):
    status = rollout.get("status", {})
    canary, bg = status.get("canary", {}), status.get("blueGreen", {})
    run = (canary.get("currentBackgroundAnalysisRunStatus") or canary.get("currentStepAnalysisRunStatus")
           or bg.get("postPromotionAnalysisRunStatus") or bg.get("prePromotionAnalysisRunStatus"))
    if not run or not run.get("name"):
        return None
    phase = run.get("status", "")
    text = phase
    if bg.get("postPromotionAnalysisRunStatus") is run:
        text = f"post-promotion {phase}"
    elif bg.get("prePromotionAnalysisRunStatus") is run:
        text = f"pre-promotion {phase}"
    try:
        ns = rollout["metadata"]["namespace"]
        ar = k8s(f"/apis/argoproj.io/v1alpha1/namespaces/{ns}/analysisruns/{run['name']}")
        for metric in ar.get("status", {}).get("metricResults", [])[:1]:
            text += f" · {metric.get('successful', 0)} ok / {metric.get('failed', 0)} failed"
    except OSError:
        pass
    return {"name": run["name"], "phase": phase, "text": text}


def pod_view(pod, info, role, now):
    meta, status = pod["metadata"], pod.get("status", {})
    container = pod["spec"]["containers"][0]
    env = {e["name"]: e.get("value") for e in container.get("env", [])}
    ready = any(c.get("ready") for c in status.get("containerStatuses", []))
    terminating = bool(meta.get("deletionTimestamp"))
    info = info or {}
    colour = info.get("colour")
    return {
        "pod": meta["name"],
        "namespace": meta["namespace"],
        "role": role,
        "revision": meta.get("labels", {}).get("rollouts-pod-template-hash", ""),
        "state": "Terminating" if terminating else ("Ready" if ready else status.get("phase", "Pending")),
        "terminating": terminating,
        "container": container["name"],
        "image": container["image"],
        "version": env.get("APP_VERSION", "?"),
        "node": pod["spec"].get("nodeName", ""),
        "podIp": status.get("podIP", ""),
        "colour": colour,
        "colourHex": PALETTE.get(colour),
        "textColour": text_colour(colour) if colour else "#ffffff",
        "healthy": info.get("healthy"),
        "age": format_age(now - info["startedAt"]) if info.get("startedAt") else "",
    }


def rollout_view(rollout, analysis, pods, infos, now):
    meta, spec, status = rollout["metadata"], rollout["spec"], rollout.get("status", {})
    ns, name = meta["namespace"], meta["name"]
    strategy = "blueGreen" if "blueGreen" in spec["strategy"] else "canary"
    steps = spec["strategy"].get("canary", {}).get("steps", [])
    index = status.get("currentStepIndex")
    step = None
    if steps and index is not None:
        detail = describe_step(steps[index]) if index < len(steps) else "complete"
        step = f"{min(index + 1, len(steps))}/{len(steps)} · {detail}"
    views = [
        pod_view(p, infos.get(p["metadata"]["uid"]),
                 pod_role(rollout, p["metadata"].get("labels", {}).get("rollouts-pod-template-hash")), now)
        for p in pods
        if p["metadata"]["namespace"] == ns and p["metadata"].get("labels", {}).get(ROLLOUT_LABEL) == name
    ]
    views.sort(key=lambda v: (ROLE_ORDER.get(v["role"], 3), v["pod"]))
    return {
        "name": name,
        "namespace": ns,
        "strategy": strategy,
        "phase": status.get("phase", "Unknown"),
        "aborted": bool(status.get("abort")),
        "message": status.get("message", ""),
        "step": step,
        "analysis": analysis,
        "release": meta.get("annotations", {}).get("octopus.com/release", ""),
        "pods": views,
    }


def build_state():
    selector = urllib.parse.quote(f"{PART_OF_KEY}={PART_OF_VALUE}")
    rollouts = k8s(f"/apis/argoproj.io/v1alpha1/rollouts?labelSelector={selector}")["items"]
    pods = k8s(f"/api/v1/pods?labelSelector={selector}")["items"]
    infos = dict(zip((p["metadata"]["uid"] for p in pods), POOL.map(fetch_info, pods)))
    analyses = list(POOL.map(analysis_summary, rollouts))
    now = time.time()
    views = [rollout_view(r, a, pods, infos, now) for r, a in zip(rollouts, analyses)]
    views.sort(key=lambda v: (v["namespace"], v["name"]))
    return {"rollouts": views, "palette": PALETTE, "failColour": FAIL_COLOUR}


class DashboardHandler(Handler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/healthz":
            return self.send(200, "ok", "text/plain")
        if path == "/":
            return self.send(200, DASHBOARD_PAGE, "text/html; charset=utf-8")
        if path == "/api/state":
            try:
                return self.send(200, build_state())
            except OSError as e:
                return self.send(502, {"error": str(e)})
        if POD_PATH.match(path):
            return self.proxy(path)
        self.send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        if POD_PATH.match(path):
            return self.proxy(path, self.read_body())
        self.send(404, {"error": "not found"})

    def proxy(self, path, data=None):
        """Forwards /pods/<namespace>/<pod>/<path> to that pod, if it's a colour-demo pod."""
        ns, name, rest = POD_PATH.match(path).groups()
        try:
            pod = k8s(f"/api/v1/namespaces/{ns}/pods/{name}")
            ip = pod.get("status", {}).get("podIP")
            if pod["metadata"].get("labels", {}).get(PART_OF_KEY) != PART_OF_VALUE or not ip:
                return self.send(404, {"error": "not a running colour-demo pod"})
            status, content_type, body = pod_http(ip, rest, data, timeout=3)
            if data is not None:
                print(f"colour change for {ns}/{name}: {data.decode(errors='replace')}", flush=True)
            self.send(status, body, content_type)
        except urllib.error.HTTPError as e:
            self.send(e.code, e.read(), e.headers.get("Content-Type", "application/json"))
        except OSError as e:
            self.send(502, {"error": str(e)})


DASHBOARD_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Colour Rollouts</title>
<style>
:root{--bg:#0f1115;--panel:#181b22;--line:#2a2f3a;--text:#e6e8ee;--muted:#9aa3b2}
*{box-sizing:border-box}
body{margin:0;padding:20px;font:14px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);color:var(--text)}
header{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 16px;margin-bottom:16px}
h1{font-size:22px;margin:0}
.muted{color:var(--muted)}
.hint b{color:#f87171}
#err{background:#7f1d1d;padding:8px 12px;border-radius:8px;margin-bottom:12px}
.rollout{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:16px}
.rhead{display:flex;flex-wrap:wrap;align-items:center;gap:8px 10px}
.rname{font-weight:650;font-size:17px}
.chip{padding:2px 9px;border-radius:999px;font-size:12px;border:1px solid var(--line);white-space:nowrap}
.phase-Healthy{background:#14532d;border-color:#22c55e}
.phase-Progressing{background:#1e3a8a;border-color:#60a5fa}
.phase-Paused{background:#713f12;border-color:#facc15}
.phase-Degraded{background:#7f1d1d;border-color:#f87171}
.analysis-Failed,.analysis-Error{background:#7f1d1d;border-color:#f87171}
.analysis-Running{border-color:#60a5fa}
.analysis-Successful{border-color:#22c55e}
.msg{margin-top:8px;font-size:13px;color:#fca5a5}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px;margin-top:12px}
.pod{position:relative;border-radius:12px;padding:12px;min-height:210px;display:flex;flex-direction:column;gap:3px;transition:background-color .4s}
.pod.terminating{opacity:.4}
.role{position:absolute;top:10px;right:10px;font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding:2px 7px;border-radius:5px;background:rgba(0,0,0,.4);color:#fff}
.role-canary,.role-preview{background:#fff;color:#111827}
.colour{font-size:24px;font-weight:700;text-transform:capitalize;padding-right:70px}
.bad{font-size:11px;font-weight:700;text-transform:uppercase;background:#000;color:#fff;padding:2px 6px;border-radius:4px;vertical-align:middle}
.kv{font-family:ui-monospace,Consolas,monospace;font-size:12px;opacity:.92;word-break:break-all}
.sw{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-top:auto;padding-top:10px}
.sw button{width:22px;height:22px;border-radius:50%;border:2px solid rgba(255,255,255,.85);padding:0;cursor:pointer}
.sw button.fail{outline:2px dashed currentColor;outline-offset:2px}
.sw button.rand{background:rgba(0,0,0,.35);color:#fff;font-size:13px;line-height:1}
.sw a{color:inherit;font-size:12px;margin-left:auto}
</style></head>
<body>
<header>
  <h1>Colour Rollouts</h1>
  <span class="hint muted">Each square is a pod. Set a canary or preview pod to <b>red</b> to fail the Argo Rollouts analysis and trigger an automatic rollback.</span>
  <span id="updated" class="muted"></span>
</header>
<div id="err" hidden></div>
<div id="rollouts"><p class="muted">Loading…</p></div>
<script>
const root = document.getElementById('rollouts');
const errBox = document.getElementById('err');
const updated = document.getElementById('updated');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

async function refresh() {
  try {
    const res = await fetch('api/state', {cache: 'no-store'});
    const state = await res.json();
    if (!res.ok) throw new Error(state.error || res.status);
    render(state);
    errBox.hidden = true;
    updated.textContent = 'updated ' + new Date().toLocaleTimeString();
  } catch (e) {
    errBox.hidden = false;
    errBox.textContent = 'Could not load cluster state: ' + e.message;
  }
}

function render(state) {
  if (!state.rollouts.length) {
    root.innerHTML = '<p class="muted">No colour-demo Rollouts yet. Deploy one of the Colour Demo projects from Octopus.</p>';
    return;
  }
  root.innerHTML = state.rollouts.map(ro => rolloutHtml(ro, state)).join('');
}

function rolloutHtml(ro, state) {
  return `<section class="rollout">
    <div class="rhead">
      <span class="rname">${esc(ro.name)}</span>
      <span class="muted">${esc(ro.namespace)}</span>
      <span class="chip">${esc(ro.strategy)}</span>
      <span class="chip phase-${esc(ro.phase)}">${esc(ro.phase)}${ro.aborted ? ' · aborted' : ''}</span>
      ${ro.step ? `<span class="chip">step ${esc(ro.step)}</span>` : ''}
      ${ro.analysis ? `<span class="chip analysis-${esc(ro.analysis.phase)}">analysis ${esc(ro.analysis.text)}</span>` : ''}
      ${ro.release ? `<span class="muted">last applied by Octopus release ${esc(ro.release)}</span>` : ''}
    </div>
    ${ro.message ? `<div class="msg">${esc(ro.message)}</div>` : ''}
    <div class="grid">${ro.pods.map(p => podHtml(p, state)).join('') || '<p class="muted">No pods</p>'}</div>
  </section>`;
}

function podHtml(p, state) {
  const target = `data-ns="${esc(p.namespace)}" data-pod="${esc(p.pod)}"`;
  const swatches = Object.entries(state.palette).map(([name, hex]) => {
    const fail = name === state.failColour;
    return `<button style="background:${hex}" class="${fail ? 'fail' : ''}" title="${name}${fail ? ' (fails analysis)' : ''}" data-colour="${name}" ${target}></button>`;
  }).join('');
  return `<div class="pod${p.terminating ? ' terminating' : ''}" style="background:${p.colourHex || '#374151'};color:${p.textColour}">
    <span class="role role-${esc(p.role)}">${esc(p.role)}</span>
    <div class="colour">${esc(p.colour || 'starting…')}${p.healthy === false ? ' <span class="bad">unhealthy</span>' : ''}</div>
    <div class="kv">${esc(p.pod)}</div>
    <div class="kv">container ${esc(p.container)} · ${esc(p.image)}</div>
    <div class="kv">version ${esc(p.version)} · rev ${esc(p.revision)}</div>
    <div class="kv">${esc(p.node)} · ${esc(p.podIp)}</div>
    <div class="kv">${esc(p.state)}${p.age ? ' · up ' + esc(p.age) : ''}</div>
    <div class="sw">${swatches}
      <button class="rand" title="Random colour" data-colour="random" ${target}>↻</button>
      <a href="pods/${esc(p.namespace)}/${esc(p.pod)}/" target="_blank" rel="noopener">page ↗</a>
    </div>
  </div>`;
}

document.addEventListener('click', async e => {
  const button = e.target.closest('button[data-colour]');
  if (!button) return;
  button.disabled = true;
  try {
    await fetch(`pods/${button.dataset.ns}/${button.dataset.pod}/api/colour`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({colour: button.dataset.colour}),
    });
  } finally {
    refresh();
  }
});

refresh();
setInterval(refresh, 1500);
</script>
</body></html>
"""


def main():
    global STATE
    if os.environ.get("MODE", "app") == "dashboard":
        handler = DashboardHandler
        print(f"dashboard listening on :{PORT}", flush=True)
    else:
        STATE = AppState()
        handler = AppHandler
        print(f"app listening on :{PORT} with colour {STATE.colour} (fail colour {FAIL_COLOUR})", flush=True)
    ThreadingHTTPServer(("", PORT), handler).serve_forever()


if __name__ == "__main__":
    main()
