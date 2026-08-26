#!/usr/bin/env python3
"""HTTP server: noVNC proxy, code-server proxy, health/stats/logs/optimizer APIs.

Security notes:
- Static file serving is hardened against path traversal (safe_join).
- Log viewer only exposes a fixed whitelist of files.
- App launcher only runs a fixed whitelist of commands.
- Optimizer only executes /usr/local/bin/optimize-system with optional --dry-run.
- Internal error details are logged server-side, never returned to clients.
"""
import asyncio
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import traceback

import aiohttp
import psutil
from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="[http-server] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

def _env_int(name, default):
    """Read an integer env var WITHOUT ever raising at import time.

    Missing / empty / garbage values all fall back to default. A raw
    int(os.environ[...]) here used to be a crash-loop vector: any empty
    PORT-style variable kills the process ~200ms after spawn.
    NOTE: must be defined before the constant block below executes.
    """
    try:
        return int(str(os.environ.get(name, "")).strip() or default)
    except (TypeError, ValueError):
        return default

# AI CLI helpers live in /usr/local/bin (copied from scripts/ by Docker).
sys.path.insert(0, "/usr/local/bin")
try:
    import ai_chat
    import ai_safety
except Exception as _ai_err:  # pragma: no cover
    ai_chat = None
    ai_safety = None
    log.warning("AI CLI module unavailable: %s", type(_ai_err).__name__)

VNC_HOST = "127.0.0.1"
VNC_PORT = 5901
CODE_HOST = "127.0.0.1"
CODE_PORT = _env_int("CODE_SERVER_PORT", 8443)
NOVNC_DIR = "/usr/share/novnc"
STATIC_DIR = "/srv"
OPTIMIZER_BIN = "/usr/local/bin/optimize-system"
OPTIMIZER_LOG = "/var/log/optimizer.log"
WALLPAPER_DIR = "/home/user/.wallpapers"
PRESET_DIR = os.path.join(WALLPAPER_DIR, "presets")
WALLPAPER_GEN = "/usr/local/bin/wallpaper-gen.py"
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

# name -> (r1,g1,b1,r2,g2,b2) gradient presets ("sinh dong")
WALLPAPER_PRESETS = {
    "midnight": (10, 14, 23, 30, 41, 59),
    "aurora": (13, 115, 119, 88, 28, 135),
    "sunset": (194, 65, 12, 190, 24, 93),
    "ocean": (8, 47, 73, 6, 182, 212),
    "neon": (76, 29, 149, 236, 72, 153),
    "forest": (6, 58, 40, 16, 185, 129),
}

PORT = _env_int("PORT", 8080)
VNC_CONNECT_WINDOW = _env_int("VNC_CONNECT_WINDOW", 120)
VNC_IDLE_TIMEOUT = _env_int("VNC_IDLE_TIMEOUT", 30)
BOOT_GRACE_SEC = _env_int("BOOT_GRACE_SEC", 240)
PROCESS_START = time.time()

stats_cache = {"data": None, "ts": 0}
health_cache = {"data": None, "ts": 0}
client_session: aiohttp.ClientSession = None

MB = 1024 * 1024


# ---------------------------------------------------------------- utilities

def _read_int(path):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except Exception:
        return None


def cgroup_mem():
    cur = _read_int("/sys/fs/cgroup/memory.current")
    if cur is None:
        cur = _read_int("/sys/fs/cgroup/memory/memory.usage_in_bytes")
        mx = _read_int("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    else:
        mx = _read_int("/sys/fs/cgroup/memory.max")
    if cur is None:
        return None, None
    if mx is None or mx > (1 << 50):
        mx = None
    return cur, mx


def safe_join(root, rel):
    """Join and verify result stays inside root (anti path-traversal)."""
    try:
        joined = os.path.realpath(os.path.join(root, rel.lstrip("/")))
        root_real = os.path.realpath(root)
        if joined == root_real or joined.startswith(root_real + os.sep):
            return joined
    except Exception:
        pass
    return None


def listening(port):
    """Check a port is LISTENing WITHOUT opening a TCP connection.

    Opening+closing raw connections to Xvnc triggers its failure
    blacklist ('Too many security failures') and can lock out real
    noVNC clients, so we read /proc/net/tcp instead.
    """
    want = f"{port:04X}"
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path) as f:
                for line in f.readlines()[1:]:
                    parts = line.split()
                    if len(parts) > 3 and parts[1].rsplit(":", 1)[1] == want \
                            and parts[3] == "0A":
                        return True
        except Exception:
            continue
    return False


def count_proc(name):
    n = 0
    me = os.getpid()
    for p in psutil.process_iter(["name"]):
        try:
            if p.pid != me and p.info["name"] == name:
                n += 1
        except Exception:
            continue
    return n


def desktop_session_proc():
    """Process name of the running desktop session (DESKTOP env)."""
    return {"xfce": "xfce4-session", "lxqt": "lxqt-session"}.get(
        os.environ.get("DESKTOP", "lxqt"), "lxqt-session")


HOP_HEADERS = {
    "host", "connection", "upgrade", "keep-alive",
    "transfer-encoding", "content-encoding", "content-length",
}


# ---------------------------------------------------------------- lifecycle

async def on_startup(app):
    global client_session
    client_session = aiohttp.ClientSession()
    create_jobs()
    asyncio.create_task(zombie_reaper())


async def cleanup(app):
    if client_session:
        await client_session.close()


async def zombie_reaper():
    while True:
        await asyncio.sleep(30)
        try:
            while True:
                pid, _ = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break
        except ChildProcessError:
            pass
        except Exception:
            pass


# ---------------------------------------------------------------- health

def check_components():
    """Return dict of component states. States: ready|starting|stopped|failed."""
    now = time.time()
    boot_grace = (now - PROCESS_START) < BOOT_GRACE_SEC

    vnc_ok = listening(VNC_PORT)
    xvnc_procs = count_proc("Xvnc")
    if vnc_ok:
        vnc_state = "ready"
    elif xvnc_procs > 0:
        vnc_state = "starting"
    else:
        vnc_state = "starting" if boot_grace else "failed"

    xfce_procs = count_proc(desktop_session_proc())
    if xfce_procs > 0:
        desktop_state = "ready"
    else:
        desktop_state = "starting" if boot_grace else "failed"

    code_state = "ready" if listening(CODE_PORT) else "stopped"

    ws_state = "ready" if listening(VNC_PORT) else "waiting"

    suspended = os.path.exists("/tmp/desktop_suspended")
    if suspended and desktop_state == "failed":
        # idle-monitor stopped the session on purpose; not a crash
        desktop_state = "suspended"

    ai_state = "ready" if _ai_ready() else "stopped"

    return {
        "http": {"state": "ready"},
        "vnc": {"state": vnc_state, "port": VNC_PORT},
        "desktop": {"state": desktop_state},
        "websocket": {"state": ws_state},
        "code_server": {"state": code_state, "port": CODE_PORT,
                        "lazy": True},
        "ai_cli": {"state": ai_state, "lazy": True},
    }


def overall_status(components):
    vnc = components["vnc"]["state"]
    desktop = components["desktop"]["state"]
    boot_grace = (time.time() - PROCESS_START) < BOOT_GRACE_SEC

    if vnc == "failed":
        return "unhealthy"
    if vnc == "ready" and desktop in ("ready", "suspended"):
        if desktop == "ready":
            return "healthy"
        return "degraded"
    if boot_grace:
        return "starting"
    if desktop == "failed":
        return "degraded"
    return "starting"


async def handle_health(request):
    now = time.time()
    if health_cache["data"] and (now - health_cache["ts"]) < 1.0:
        data, status_code = health_cache["data"]
        return web.json_response(data, status=status_code)

    components = check_components()
    overall = overall_status(components)

    uptime_s = int(now - PROCESS_START)
    d, h = divmod(uptime_s, 86400)
    h2, m = divmod(h, 3600)
    m2, s = divmod(m, 60)

    data = {
        "status": overall,
        "vnc": components["vnc"]["state"],
        "desktop": components["desktop"]["state"],
        "websocket": components["websocket"]["state"],
        "code_server": components["code_server"]["state"],
        "components": components,
        "uptime_seconds": uptime_s,
        "uptime": f"{d}d {h2}h {m2}m {s}s" if d else f"{h2}h {m2}m {s}s",
        "timestamp": int(now),
    }

    status_code = 503 if overall == "unhealthy" else 200
    health_cache["data"] = (data, status_code)
    health_cache["ts"] = now
    return web.json_response(data, status=status_code)


# ---------------------------------------------------------------- stats

def collect_stats():
    now = time.time()
    if stats_cache["data"] and (now - stats_cache["ts"]) < 1.5:
        return stats_cache["data"]

    try:
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage("/")
        cpu_freq = psutil.cpu_freq()
        net = psutil.net_io_counters()
        load = os.getloadavg()
        uptime_s = time.time() - psutil.boot_time()
    except Exception as e:
        log.warning("collect_stats base error: %s", e)
        return stats_cache["data"] or {}

    cg_used, cg_limit = cgroup_mem()
    if cg_used is not None:
        mem_total = cg_limit if cg_limit else mem.total
        mem_used = min(cg_used, mem_total)
        mem_percent = round(mem_used / mem_total * 100, 1)
    else:
        mem_total = mem.total
        mem_used = mem.used
        mem_percent = mem.percent

    days = int(uptime_s // 86400)
    hours = int((uptime_s % 86400) // 3600)
    mins = int((uptime_s % 3600) // 60)

    wifi_info = None
    try:
        r = subprocess.run(
            ["sh", "-c", "cat /proc/net/wireless 2>/dev/null | tail -n +3"],
            capture_output=True, text=True, timeout=2,
        )
        if r.stdout.strip():
            r2 = subprocess.run(
                ["iw", "dev", "wlan0", "link"],
                capture_output=True, text=True, timeout=2,
            )
            for line in r2.stdout.splitlines():
                line = line.strip()
                if line.startswith("SSID:"):
                    wifi_info = line.split(":", 1)[1].strip()
                elif "signal:" in line:
                    sig = line.split("signal:", 1)[1].strip()
                    wifi_info = f"{wifi_info or 'Unknown'} ({sig})"
    except Exception:
        pass

    idle_ms = 0
    suspended = os.path.exists("/tmp/desktop_suspended")
    try:
        idle_out = subprocess.check_output(
            ["/usr/bin/xprintidle"],
            env={"DISPLAY": os.environ.get("DISPLAY", ":1")},
            timeout=3,
        )
        idle_ms = int(idle_out.strip())
    except Exception:
        pass

    # FPS is NOT fabricated. Real per-frame FPS is not exposed by Xvnc;
    # report null and let the UI show N/A.
    fps = None

    stats = {
        "cpu_percent": psutil.cpu_percent(interval=0),
        "cpu_count": psutil.cpu_count(),
        "cpu_freq": round(cpu_freq.current, 0) if cpu_freq else 0,
        "load_1": round(load[0], 2),
        "load_5": round(load[1], 2),
        "load_15": round(load[2], 2),
        "mem_total": mem_total,
        "mem_used": mem_used,
        "mem_percent": mem_percent,
        "mem_limit_mb": (cg_limit // MB) if cg_limit else _env_int("MEM_LIMIT_MB", 1228),
        "swap_total": swap.total,
        "swap_used": swap.used,
        "swap_percent": swap.percent,
        "disk_total": disk.total,
        "disk_used": disk.used,
        "disk_percent": disk.percent,
        "net_sent": net.bytes_sent,
        "net_recv": net.bytes_recv,
        "wifi": wifi_info,
        "uptime": f"{days}d {hours}h {mins}m",
        "uptime_seconds": int(uptime_s),
        "processes": len(psutil.pids()),
        "idle_ms": idle_ms,
        "suspended": suspended,
        "idle_suspend_enabled": _env_int("IDLE_TIMEOUT", 0) > 0,
        "resolution": os.environ.get("RESOLUTION", ""),
        "fps": fps,
        "timestamp": int(now),
    }
    stats_cache["data"] = stats
    stats_cache["ts"] = now
    return stats


async def handle_index(request):
    return web.FileResponse(os.path.join(STATIC_DIR, "index.html"))


async def handle_stats(request):
    return web.json_response(collect_stats())


async def handle_session(request):
    """VNC session info for the web UI.

    Exposes the password ONLY when it is the well-known default (admin did
    not set a custom VNC_PASSWORD). Custom passwords are never sent to the
    browser - noVNC will show its own password prompt instead.
    """
    pw = os.environ.get("VNC_PASSWORD", "")
    defaulted = os.environ.get("VNC_PASSWORD_DEFAULTED", "") == "1"
    return web.json_response({
        "auth": bool(pw),
        "password": pw if (pw and defaulted) else None,
    })


async def vnc_client_info(request):
    """Info for connecting with a REAL VNC client (RealVNC/TigerVNC/RVNC).

    - public_mode: Xvnc listens on 0.0.0.0 (needs VNC_PUBLIC=1)
    - tcp_proxy:   the Railway TCP Proxy address, set via VNC_TCP_PROXY
                   env after creating the proxy for port 5901
    - ips:         container-internal IPs (usable only inside the same
                   Railway network / not from a home PC)
    Password follows the same policy as /api/session: only shown when it
    is the well-known default.
    """
    import socket
    pub = os.environ.get("VNC_PUBLIC", "0") == "1"
    proxy = os.environ.get("VNC_TCP_PROXY", "").strip()

    ips = []
    try:
        hn = socket.gethostbyname(socket.gethostname())
        if hn and not hn.startswith("127.") and hn not in ips:
            ips.append(hn)
    except Exception:
        pass
    try:
        for _iface, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == socket.AF_INET and \
                        not a.address.startswith("127.") and \
                        a.address not in ips:
                    ips.append(a.address)
    except Exception:
        pass

    pw = os.environ.get("VNC_PASSWORD", "")
    defaulted = os.environ.get("VNC_PASSWORD_DEFAULTED", "") == "1"

    addr = proxy if proxy else ""
    return web.json_response({
        "public_mode": pub,
        "tcp_proxy": proxy,
        "address": addr,
        "ips": ips[:4],
        "vnc_port": VNC_PORT,
        "auth": bool(pw),
        "password": pw if (pw and defaulted) else None,
        "resolution": os.environ.get("RESOLUTION", ""),
    })


async def handle_services(request):
    components = check_components()
    label = {"ready": "READY", "starting": "STARTING",
             "stopped": "STOPPED", "failed": "FAILED",
             "suspended": "WARNING", "waiting": "STARTING"}
    services = {k: label.get(v["state"], v["state"].upper())
                for k, v in components.items()}
    return web.json_response({"services": services})


# ---------------------------------------------------------------- static

async def handle_novnc(request):
    rel = request.match_info.get("path", "")
    fpath = safe_join(NOVNC_DIR, rel)
    if fpath and os.path.isfile(fpath):
        return web.FileResponse(fpath)
    return web.Response(status=404)


# ---------------------------------------------------------------- app launcher

APPS = {
    "terminal": "export DISPLAY=:1; exec xfce4-terminal --default-working-directory=/home/user",
    "firefox": "export DISPLAY=:1; exec firefox-esr",
    "chromium": "export DISPLAY=:1; exec chromium --no-sandbox --disable-dev-shm-usage",
    "files": "export DISPLAY=:1; exec thunar /home/user",
}


async def launch_app(request):
    name = request.match_info.get("name", "")
    cmd = APPS.get(name)
    if not cmd:
        return web.json_response({"status": "error",
                                  "msg": "unknown app"}, status=404)
    try:
        subprocess.Popen(
            ["su", "-", "user", "-c", cmd],
            start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        return web.json_response({"status": "launched", "app": name})
    except Exception as e:
        log.warning("launch_app %s failed: %s", name, e)
        return web.json_response({"status": "error",
                                  "msg": "launch failed"}, status=500)


# ---------------------------------------------------------------- code-server

async def start_code_server(request):
    """Lazy-start code-server and wait until its port answers."""
    if listening(CODE_PORT):
        return web.json_response({"status": "ready"})
    try:
        subprocess.Popen(
            ["supervisorctl", "start", "code-server"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        log.warning("code-server start trigger failed: %s", e)
        return web.json_response({"status": "error",
                                  "msg": "start failed"}, status=500)

    deadline = time.time() + _env_int("CODE_START_TIMEOUT", 30)
    while time.time() < deadline:
        await asyncio.sleep(1.5)
        if request.transport is None or request.transport.is_closing():
            return web.json_response({"status": "starting"})
        if listening(CODE_PORT):
            return web.json_response({"status": "ready"})
    return web.json_response({"status": "timeout"}, status=202)


def filter_headers(headers):
    return {k: v for k, v in headers.items() if k.lower() not in HOP_HEADERS}


# ---------------------------------------------------------------- proxies

async def code_ws_bridge(req, path):
    ws_server = web.WebSocketResponse(max_msg_size=16 * 1024 * 1024,
                                      heartbeat=25)
    await ws_server.prepare(req)

    qs = f"?{req.query_string}" if req.query_string else ""
    url = f"ws://{CODE_HOST}:{CODE_PORT}/{path}{qs}"
    try:
        session = aiohttp.ClientSession()
        # NOTE: do NOT use aiohttp.ClientWSTimeout here - it requires
        # aiohttp >= 3.9 while Debian bookworm ships 3.8. Heartbeat below
        # already detects dead peers.
        connect_kw = {"max_msg_size": 0}
        if hasattr(aiohttp, "ClientWSTimeout"):
            connect_kw["timeout"] = aiohttp.ClientWSTimeout(ws_close_timeout=10)
        ws_client = await session.ws_connect(url, **connect_kw)
    except Exception as e:
        log.warning("code-server WS connect failed: %s", e)
        await ws_server.close(code=1011, message=b"backend unavailable")
        return ws_server

    async def c2r():
        async for msg in ws_server:
            if msg.type == web.WSMsgType.TEXT:
                await ws_client.send_str(msg.data)
            elif msg.type == web.WSMsgType.BINARY:
                await ws_client.send_bytes(msg.data)
            else:
                break

    async def r2c():
        async for msg in ws_client:
            if msg.type == web.WSMsgType.TEXT:
                await ws_server.send_str(msg.data)
            elif msg.type == web.WSMsgType.BINARY:
                await ws_server.send_bytes(msg.data)
            else:
                break

    await asyncio.gather(c2r(), r2c(), return_exceptions=True)
    try:
        await ws_client.close()
    finally:
        await session.close()
    await ws_server.close()
    return ws_server


async def code_proxy(req):
    path = req.match_info.get("path", "")

    if req.headers.get("Upgrade", "").lower() == "websocket":
        return await code_ws_bridge(req, path)

    qs = f"?{req.query_string}" if req.query_string else ""
    url = f"http://{CODE_HOST}:{CODE_PORT}/{path}{qs}"

    body = None
    if req.method in ("POST", "PUT", "PATCH"):
        body = await req.read()

    if client_session is None:
        return web.Response(status=502, text="proxy not ready")

    try:
        async with client_session.request(
            req.method, url, data=body,
            headers=filter_headers(req.headers),
            allow_redirects=False, timeout=aiohttp.ClientTimeout(total=60),
        ) as r:
            data = await r.read()
            headers = {k: v for k, v in r.headers.items()
                       if k.lower() not in HOP_HEADERS}
            return web.Response(status=r.status, body=data, headers=headers)
    except Exception:
        return web.Response(
            status=502,
            text="<h1>VS Code chua khoi dong</h1>"
                 "<p>Bam nut VS Code o sidebar de bat dau.</p>",
            content_type="text/html",
        )


# ---------------------------------------------------------------- VNC bridge

async def vnc_ws_handler(request):
    """Raw WebSocket <-> TCP bridge to Xvnc.

    - Retries TCP connect up to VNC_CONNECT_WINDOW seconds so that opening
      the page before Xvnc is up does NOT hard-fail.
    - Closes cleanly on either side EOF; no infinite hang (heartbeat +
      connect deadline).
    """
    ws_server = web.WebSocketResponse(max_msg_size=0, compress=False,
                                      heartbeat=15, autoping=True)
    await ws_server.prepare(request)

    deadline = time.time() + max(10, VNC_CONNECT_WINDOW)
    reader = None
    writer = None
    last_err = ""
    while True:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(VNC_HOST, VNC_PORT), timeout=5)
            break
        except Exception as e:
            last_err = type(e).__name__
            if ws_server.closed or time.time() >= deadline:
                log.warning("VNC connect failed after retries: %s", last_err)
                try:
                    await ws_server.close(code=1013,
                                          message=b"vnc not available")
                except Exception:
                    pass
                return ws_server
            try:
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                return ws_server

    async def client_to_vnc():
        try:
            async for msg in ws_server:
                if msg.type == web.WSMsgType.TEXT:
                    writer.write(msg.data.encode())
                elif msg.type == web.WSMsgType.BINARY:
                    writer.write(msg.data)
                elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
                    break
            await writer.drain()
        except Exception:
            pass

    async def vnc_to_client():
        try:
            while True:
                # Idle timeout: real noVNC clients poll for updates every
                # second, so total silence in BOTH directions means a dead
                # peer. Without this, leaked VNC connections pile up and
                # TigerVNC stops serving new handshakes.
                data = await asyncio.wait_for(
                    reader.read(65536), timeout=VNC_IDLE_TIMEOUT)
                if not data:
                    break
                await ws_server.send_bytes(data)
        except asyncio.TimeoutError:
            log.info("VNC bridge idle timeout, closing")
        except Exception:
            pass

    t1 = asyncio.create_task(client_to_vnc())
    t2 = asyncio.create_task(vnc_to_client())
    # Tear down as soon as EITHER side finishes; cancel the sibling so no
    # zombie VNC connection survives a vanished browser.
    done, pending = await asyncio.wait({t1, t2},
                                       return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
    await asyncio.gather(*done, *pending, return_exceptions=True)

    for t in (t1, t2):
        if not t.done():
            t.cancel()
    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass
    if not ws_server.closed:
        try:
            await ws_server.close(code=1000, message=b"session ended")
        except Exception:
            pass
    return ws_server


# ---------------------------------------------------------------- logs API

LOG_WHITELIST = {
    "system": "/var/log/supervisor/supervisord.log",
    "boot": "/var/log/boot.log",
    "vnc": "/var/log/supervisor/xvnc.log",
    "xfce": "/var/log/supervisor/desktop.log",
    "watchdog": "/var/log/supervisor/watchdog.log",
    "optimizer": "/var/log/optimizer.log",
    "code-server": "/var/log/supervisor/code-server.log",
    "backup": "/var/log/supervisor/autobackup.log",
}
MAX_LOG_TAIL = 256 * 1024


def _tail_file(path, lines, max_bytes=MAX_LOG_TAIL):
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
            data = f.read().decode("utf-8", errors="replace")
        out = data.splitlines()[-lines:]
        return "\n".join(out)
    except FileNotFoundError:
        return "(log file not found)"
    except Exception as e:
        log.warning("tail_file %s: %s", path, type(e).__name__)
        return "(error reading log)"


async def logs_list(request):
    avail = {}
    for name, path in LOG_WHITELIST.items():
        try:
            avail[name] = {"path": path, "size": os.path.getsize(path)}
        except Exception:
            avail[name] = {"path": path, "size": 0}
    return web.json_response({"logs": avail})


async def logs_view(request):
    name = request.match_info.get("name", "")
    path = LOG_WHITELIST.get(name)
    if not path:
        return web.json_response({"status": "error",
                                  "msg": "unknown log"}, status=404)
    try:
        lines = min(max(int(request.query.get("lines", "200")), 10), 500)
    except ValueError:
        lines = 200
    return web.json_response({
        "name": name,
        "content": _tail_file(path, lines),
    })


async def logs_clear(request):
    name = request.match_info.get("name", "")
    path = LOG_WHITELIST.get(name)
    if not path:
        return web.json_response({"status": "error",
                                  "msg": "unknown log"}, status=404)
    try:
        with open(path, "r+") as f:
            f.truncate(0)
        return web.json_response({"status": "cleared", "name": name})
    except FileNotFoundError:
        return web.json_response({"status": "cleared", "name": name})
    except Exception as e:
        log.warning("logs_clear %s: %s", name, type(e).__name__)
        return web.json_response({"status": "error",
                                  "msg": "clear failed"}, status=500)


# ---------------------------------------------------------------- optimizer

class OptimizerJob:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.running = False
        self.dry_run = False
        self.started_at = 0
        self.buffered = []          # recent lines for late subscribers
        self.subscribers = set()
        self.result = None
        self.proc = None

    async def start(self, dry_run):
        async with self.lock:
            if self.running:
                return False, "already running"
            self.running = True
            self.dry_run = bool(dry_run)
            self.started_at = time.time()
            self.buffered.clear()
            self.result = None
            args = [OPTIMIZER_BIN]
            if self.dry_run:
                args.append("--dry-run")
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env={**os.environ},
                )
            except Exception as e:
                self.running = False
                log.error("optimizer spawn failed: %s", e)
                return False, "spawn failed"
            asyncio.create_task(self._pump())
            return True, "started"

    async def broadcast(self, line):
        entry = {"ts": int(time.time()), "line": line}
        self.buffered.append(entry)
        if len(self.buffered) > 800:
            del self.buffered[:200]
        for q in list(self.subscribers):
            try:
                q.put_nowait(entry)
            except Exception:
                self.subscribers.discard(q)

    async def finish(self, returncode):
        self.running = False
        self.returncode = returncode
        await self.broadcast(
            f"[OPTIMIZER] exited rc={returncode}")

    async def _pump(self):
        assert self.proc and self.proc.stdout
        deadline = time.time() + 900  # hard cap 15 minutes
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    self.proc.kill()
                    await self.broadcast("[OPTIMIZER] timeout, killed")
                    break
                try:
                    raw = await asyncio.wait_for(
                        self.proc.stdout.readline(), timeout=remaining)
                except asyncio.TimeoutError:
                    continue
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip()
                if line.startswith("OPT_RESULT_JSON:"):
                    try:
                        self.result = json.loads(line.split(":", 1)[1])
                    except Exception:
                        self.result = None
                    continue
                await self.broadcast(line)
        except Exception as e:
            await self.broadcast(f"[OPTIMIZER] pump error {type(e).__name__}")
        rc = await self.proc.wait()
        await self.finish(rc)


# Created lazily in on_startup(): the constructor builds asyncio.Lock(),
# which must not be instantiated before an event loop exists (it would
# bind to a different/absent loop on some Python versions).
optimizer: "OptimizerJob" = None


async def optimize_run(request):
    dry_run = request.query.get("dry_run", "0") == "1"
    ok, msg = await optimizer.start(dry_run)
    if not ok:
        return web.json_response({"status": msg}, status=409)
    return web.json_response({"status": "started", "dry_run": dry_run})


async def optimize_status(request):
    return web.json_response({
        "running": optimizer.running,
        "dry_run": optimizer.dry_run,
        "result": optimizer.result,
        "returncode": getattr(optimizer, "returncode", None),
    })


async def optimize_stream(request):
    resp = web.StreamResponse(status=200, headers={
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })
    await resp.prepare(request)

    queue: asyncio.Queue = asyncio.Queue()
    for entry in optimizer.buffered[-300:]:
        await queue.put(entry)
    optimizer.subscribers.add(queue)

    try:
        await resp.write(b": connected\n\n")
        while True:
            try:
                entry = await asyncio.wait_for(queue.get(), timeout=15)
                payload = json.dumps(entry)
                await resp.write(f"data: {payload}\n\n".encode())
                if "[OPTIMIZER] exited" in entry["line"]:
                    await resp.write(b"data: __END__\n\n")
                    break
            except asyncio.TimeoutError:
                await resp.write(b": keepalive\n\n")
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        optimizer.subscribers.discard(queue)
    return resp


# ---------------------------------------------------------------- tasks
# Generic terminal-task runner (install VS Code, OS profile "buff", ...).
# One job at a time; output is streamed to subscribers over SSE and
# buffered so late viewers see the history.

TERMINAL_TASKS = {
    "vscode": {
        "title": "Cai Visual Studio Code (PC)",
        "argv": ["/usr/local/bin/install-vscode"],
    },
}

# Resolve real script paths: Docker copies scripts/ keeping the .sh suffix,
# but also creates friendly aliases (install-vscode, os-profile) in the
# Dockerfile - accept either so a rebuild is never needed for this.
def _script_path(name):
    for cand in (f"/usr/local/bin/{name}", f"/usr/local/bin/{name}.sh"):
        if os.path.exists(cand):
            return cand
    return f"/usr/local/bin/{name}"


for _t in TERMINAL_TASKS.values():
    _t["argv"] = [_script_path(os.path.basename(_t["argv"][0]))]

OS_PROFILES = {
    "lite": {
        "title": "OS Lite Sieu Nhe",
        "desc": "Giu LXQt mac dinh (nhe - dep - on dinh), don dep + "
                "tinh chinh hieu nang. Khong tai them gi.",
    },
    "dev": {
        "title": "Developer Day Du",
        "desc": "gcc/cmake, jq, ripgrep, fzf, tmux, sqlite3, strace, "
                "python venv/pip, dnsutils... cho lap trinh vien.",
    },
    "media": {
        "title": "Media & Design",
        "desc": "Inkscape, Krita, Audacity, mpv, HandBrake - chup anh, "
                "nghe nhac, convert video.",
    },
    "drivers": {
        "title": "Driver & Phan Cung",
        "desc": "FUSE + gvfs, NTFS/exFAT, USB/PCI tools, SMART, lm-sensors, "
                "CIFS/NFS client.",
    },
    "ultra": {
        "title": "BUFF TAT CA",
        "desc": "dev + media + drivers trong mot luot. Tai nhieu nhat "
                "(~500MB+), chay lau hon.",
    },
}


class TaskJob:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.running = False
        self.name = ""
        self.title = ""
        self.started_at = 0
        self.buffered = []
        self.subscribers = set()
        self.result = None

    async def start(self, name, title, argv):
        async with self.lock:
            if self.running:
                return False, f"'{self.name}' dang chay"
            self.running = True
            self.name = name
            self.title = title
            self.started_at = time.time()
            self.buffered.clear()
            self.result = None
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    *argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env={**os.environ},
                )
            except Exception as e:
                self.running = False
                log.error("task %s spawn failed: %s", name, e)
                return False, "spawn failed"
            asyncio.create_task(self._pump())
            return True, "started"

    async def broadcast(self, line):
        entry = {"ts": int(time.time()), "line": line}
        self.buffered.append(entry)
        if len(self.buffered) > 800:
            del self.buffered[:200]
        for q in list(self.subscribers):
            try:
                q.put_nowait(entry)
            except Exception:
                self.subscribers.discard(q)

    async def finish(self, returncode):
        self.running = False
        self.returncode = returncode
        await self.broadcast(f"[TASK] '{self.name}' exited rc={returncode}")

    async def _pump(self):
        assert self.proc and self.proc.stdout
        deadline = time.time() + 3600  # hard cap 1 hour (ultra profile)
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    self.proc.kill()
                    await self.broadcast("[TASK] timeout, killed")
                    break
                try:
                    raw = await asyncio.wait_for(
                        self.proc.stdout.readline(), timeout=remaining)
                except asyncio.TimeoutError:
                    continue
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip()
                if line.startswith("TASK_RESULT_JSON:"):
                    try:
                        self.result = json.loads(line.split(":", 1)[1])
                    except Exception:
                        self.result = None
                    continue
                await self.broadcast(line)
        except Exception as e:
            await self.broadcast(f"[TASK] pump error {type(e).__name__}")
        rc = await self.proc.wait()
        await self.finish(rc)


task_job: "TaskJob" = None


def create_jobs():
    """Instantiate background jobs once the loop is up (see note above)."""
    global optimizer, task_job
    if optimizer is None:
        optimizer = OptimizerJob()
    if task_job is None:
        task_job = TaskJob()


async def tasks_status(request):
    return web.json_response({
        "running": task_job.running,
        "name": task_job.name,
        "title": task_job.title,
        "result": task_job.result,
        "returncode": getattr(task_job, "returncode", None),
    })


async def tasks_run(request):
    task = request.match_info.get("task", "")
    if task == "os":
        profile = request.query.get("profile", "lite")
        meta = OS_PROFILES.get(profile)
        if not meta:
            return web.json_response(
                {"status": "error", "msg": "unknown profile"}, status=404)
        argv = [_script_path("os-profile"), profile]
        title = meta["title"]
        name = f"os:{profile}"
    elif task in TERMINAL_TASKS:
        meta = TERMINAL_TASKS[task]
        argv = list(meta["argv"])
        title = meta["title"]
        name = task
    else:
        return web.json_response({"status": "error",
                                  "msg": "unknown task"}, status=404)

    if not os.path.exists(argv[0]):
        log.error("task %s: script missing: %s", name, argv[0])
        return web.json_response(
            {"status": "error", "msg": f"script khong ton tai: {argv[0]}"},
            status=500)

    ok, msg = await task_job.start(name, title, argv)
    if not ok:
        return web.json_response({"status": msg}, status=409)
    log.info("task started: %s (%s)", name, " ".join(argv))
    return web.json_response({"status": "started", "task": name})


async def tasks_stream(request):
    resp = web.StreamResponse(status=200, headers={
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })
    await resp.prepare(request)

    queue: asyncio.Queue = asyncio.Queue()
    for entry in task_job.buffered[-300:]:
        await queue.put(entry)
    task_job.subscribers.add(queue)

    try:
        await resp.write(b": connected\n\n")
        while True:
            try:
                entry = await asyncio.wait_for(queue.get(), timeout=15)
                payload = json.dumps(entry)
                await resp.write(f"data: {payload}\n\n".encode())
                if "[TASK] '" in entry["line"] and "exited" in entry["line"]:
                    await resp.write(b"data: __END__\n\n")
                    break
            except asyncio.TimeoutError:
                if not task_job.running and task_job.buffered:
                    # job finished while we were subscribed -> end cleanly
                    last = task_job.buffered[-1]["line"]
                    if "[TASK] '" in last and "exited" in last:
                        await resp.write(b"data: __END__\n\n")
                        break
                await resp.write(b": keepalive\n\n")
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        task_job.subscribers.discard(queue)
    return resp


async def os_profiles(request):
    profiles = []
    for key, meta in OS_PROFILES.items():
        done_marker = os.path.join("/home/user/.config/os-profiles",
                                   key + ".done")
        profiles.append({"id": key, "title": meta["title"],
                         "desc": meta["desc"],
                         "applied": os.path.exists(done_marker)})
    return web.json_response({"profiles": profiles})


# ---------------------------------------------------------------- AI CLI

def _ai_ready():
    return ai_chat is not None and ai_safety is not None and \
        ai_chat.enabled()


async def ai_status(request):
    if ai_chat is None:
        return web.json_response({"enabled": False})
    cfg = ai_chat.load_config()
    return web.json_response({
        "enabled": ai_chat.enabled(cfg),
        "name": cfg.get("name"),
        "model": cfg.get("model"),
        "provider": cfg.get("provider") or "openai",
    })


async def ai_chat_handler(request):
    if not _ai_ready():
        return web.json_response({"status": "disabled"}, status=503)
    try:
        body = await request.json()
        prompt = str(body.get("prompt", "")).strip()
    except Exception:
        return web.json_response({"status": "error",
                                  "msg": "bad request"}, status=400)
    if not prompt:
        return web.json_response({"status": "error",
                                  "msg": "empty prompt"}, status=400)
    if len(prompt) > 8000:
        return web.json_response({"status": "error",
                                  "msg": "prompt qua dai (max 8000)"},
                                 status=413)

    cfg = ai_chat.load_config()
    try:
        reply = await asyncio.to_thread(
            ai_chat.chat, cfg, prompt, 120)
    except Exception as e:
        log.warning("AI chat error: %s", type(e).__name__)
        msg = str(e)[:300]
        return web.json_response({"status": "error", "msg": msg}, status=502)

    commands = []
    for c in ai_chat.extract_commands(reply):
        ok, why = ai_safety.classify_command(c)
        commands.append({"cmd": c, "ok": ok, "reason": "" if ok else why})
    return web.json_response({"status": "ok", "reply": reply,
                              "commands": commands})


MAX_EXEC_OUTPUT = 256 * 1024


async def ai_exec(request):
    """Run ONE command proposed by the AI - only after passing the
    safety filter (blocks rm -rf /, mkfs, dd to /dev/*, shutdown,
    killing platform services, tampering with /etc/supervisor...).

    Commands run as the desktop user ('user') - not root - so files
    created in /home/user keep correct ownership; the user has
    passwordless sudo for anything that genuinely needs root.
    """
    if not _ai_ready():
        return web.json_response({"status": "disabled"}, status=503)
    try:
        body = await request.json()
        cmd = str(body.get("command", "")).strip()
    except Exception:
        return web.json_response({"status": "error",
                                  "msg": "bad request"}, status=400)
    if not cmd:
        return web.json_response({"denied": True, "reason": "lenh rong"},
                                 status=400)

    ok, reason = ai_safety.classify_command(cmd)
    if not ok:
        log.info("AI exec DENIED (%s): %.80s", reason, cmd)
        return web.json_response({"denied": True, "reason": reason})

    try:
        timeout = int(os.environ.get("AI_EXEC_TIMEOUT", "240"))
    except ValueError:
        timeout = 240

    import signal
    import pwd

    def _demote():
        pw = pwd.getpwnam("user")
        os.setgroups([])
        os.setgid(pw.pw_gid)
        os.setuid(pw.pw_uid)

    started = time.time()
    # Correct HOME/USER must be in env BEFORE bash -l reads the profile,
    # otherwise the login shell picks up root's HOME (/root) and errors.
    # 'cd /home/user' guards against odd profiles that change directory.
    child_env = {**os.environ}
    child_env.update({
        "DISPLAY": ":1",
        "HOME": "/home/user",
        "USER": "user",
        "LOGNAME": "user",
    })
    proc = await asyncio.create_subprocess_exec(
        "bash", "-lc", "cd /home/user 2>/dev/null; " + cmd,
        cwd="/home/user",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=child_env,
        preexec_fn=_demote,
        start_new_session=True,
    )
    timed_out = False
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        timed_out = True
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        out = b"(timeout - lenh bi huy sau %d giay)\n" % timeout

    output = out[-MAX_EXEC_OUTPUT:].decode("utf-8", errors="replace")
    return web.json_response({
        "denied": False,
        "rc": 124 if timed_out else proc.returncode,
        "output": output,
        "duration_s": int(time.time() - started),
    })


# ---------------------------------------------------------------- wallpaper

def _run_as_user_bg(cmd):
    """Run a shell command as the desktop user inside the X session."""
    try:
        subprocess.Popen(
            ["su", "-", "user", "-c", "export DISPLAY=:1; " + cmd],
            start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL)
    except Exception as e:
        log.warning("run_as_user failed: %s", type(e).__name__)


def _apply_wallpaper(path):
    de = os.environ.get("DESKTOP", "lxqt")
    safe = shlex.quote(path)
    if de == "xfce":
        prop = "/backdrop/screen0/monitor0/workspace0/last-image"
        _run_as_user_bg(
            "timeout 10 xfconf-query -c xfce4-desktop -p " + prop +
            " -t string -s " + safe + " --create -n")
    else:
        # LXQt: pcmanfm-qt desktop wallpaper
        conf = "/home/user/.config/pcmanfm-qt/lxqt/settings.conf"
        os.makedirs(os.path.dirname(conf), exist_ok=True)
        try:
            if os.path.exists(conf):
                with open(conf) as f:
                    lines = [l for l in f.readlines()
                             if not l.startswith(("Wallpaper=", "WallpaperMode="))]
                if not any(l.strip() == "[General]" for l in lines):
                    lines.insert(0, "[General]\n")
            else:
                lines = ["[General]\n"]
            lines.append("Wallpaper=" + path + "\n")
            lines.append("WallpaperMode=stretch\n")
            tmp = conf + ".tmp"
            with open(tmp, "w") as f:
                f.writelines(lines)
            os.replace(tmp, conf)
            subprocess.run(["chown", "user:user", conf], timeout=5)
        except Exception as e:
            log.warning("pcmanfm wallpaper config: %s", type(e).__name__)
            return False
        subprocess.run(["pkill", "-f", "pcmanfm-qt"], timeout=5)
        time.sleep(0.6)
        _run_as_user_bg("exec pcmanfm-qt --desktop >/dev/null 2>&1 &")
    try:
        with open(os.path.join(WALLPAPER_DIR, "CURRENT"), "w") as f:
            f.write(path)
    except Exception:
        pass
    return True


def current_wallpaper():
    try:
        with open(os.path.join(WALLPAPER_DIR, "CURRENT")) as f:
            p = f.read().strip()
            if p and os.path.isfile(p):
                return p
    except Exception:
        pass
    return ""


async def wallpaper_list(request):
    presets = []
    for name in WALLPAPER_PRESETS:
        p = os.path.join(PRESET_DIR, name + ".png")
        presets.append({"name": name, "exists": os.path.isfile(p),
                        "colors": WALLPAPER_PRESETS[name]})
    cpath = ""
    for ext in (".png", ".jpg", ".gif", ".webp"):
        cand = os.path.join(WALLPAPER_DIR, "custom" + ext)
        if os.path.isfile(cand):
            cpath = cand
            break
    return web.json_response({
        "presets": presets, "custom": cpath, "current": current_wallpaper()})


async def wallpaper_preset(request):
    try:
        body = await request.json()
        name = str(body.get("name", ""))
    except Exception:
        return web.json_response({"status": "error",
                                  "msg": "bad request"}, status=400)
    if name not in WALLPAPER_PRESETS:
        return web.json_response({"status": "error",
                                  "msg": "unknown preset"}, status=404)
    os.makedirs(PRESET_DIR, exist_ok=True)
    out = os.path.join(PRESET_DIR, name + ".png")
    m = re.match(r"^(\d{2,5})x(\d{2,5})$",
                 (os.environ.get("RESOLUTION") or "").strip())
    w, h = (int(m.group(1)), int(m.group(2))) if m else (1600, 900)
    cmd = ["python3", WALLPAPER_GEN, out, str(w), str(h)] + \
        [str(c) for c in WALLPAPER_PRESETS[name]]
    try:
        r = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT)
        await asyncio.wait_for(r.wait(), timeout=30)
    except Exception as e:
        log.warning("preset gen failed: %s", type(e).__name__)
        return web.json_response({"status": "error",
                                  "msg": "generate failed"}, status=500)
    if r.returncode != 0 or not os.path.isfile(out):
        return web.json_response({"status": "error",
                                  "msg": "generate failed"}, status=500)
    ok = _apply_wallpaper(out)
    return web.json_response({"status": "applied" if ok else "error",
                              "wallpaper": out})


MAGIC = [(b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"),
         (b"GIF8", ".gif")]


def _image_ext(data):
    for sig, ext in MAGIC:
        if data.startswith(sig):
            return ext
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return ".webp"
    return None


async def wallpaper_upload(request):
    try:
        reader = await request.multipart()
    except Exception:
        return web.json_response({"status": "error",
                                  "msg": "multipart required"}, status=400)
    field = None
    while True:
        part = await reader.next()
        if part is None:
            break
        if getattr(part, "name", "") == "file":
            field = part
            break
    if field is None:
        return web.json_response({"status": "error",
                                  "msg": "file field missing"}, status=400)
    data = bytearray()
    while True:
        chunk = await field.read_chunk(65536)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_UPLOAD_BYTES:
            return web.json_response({"status": "error",
                                      "msg": "too large (max 8MB)"}, status=413)
    ext = _image_ext(bytes(data[:16]))
    if not ext:
        return web.json_response({"status": "error",
                                  "msg": "not an image"}, status=400)
    for old in ("custom.png", "custom.jpg", "custom.gif", "custom.webp"):
        p = os.path.join(WALLPAPER_DIR, old)
        if old != "custom" + ext and os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
    out = os.path.join(WALLPAPER_DIR, "custom" + ext)
    try:
        with open(out, "wb") as f:
            f.write(bytes(data))
        subprocess.run(["chown", "user:user", out], timeout=5)
    except Exception:
        return web.json_response({"status": "error",
                                  "msg": "save failed"}, status=500)
    ok = _apply_wallpaper(out)
    return web.json_response({"status": "applied" if ok else "error",
                              "wallpaper": out})

# ---------------------------------------------------------------- power

async def system_power(request):
    """Restart the desktop session or reboot the whole container.

    Requires confirm=really to avoid accidental triggers.
    Reboot: backup -> supervisorctl shutdown -> container exits ->
    Railway ALWAYS policy restarts it with data intact on the volume.
    """
    action = request.match_info.get("action", "")
    if request.query.get("confirm", "") != "really":
        return web.json_response({"status": "error",
                                  "msg": "missing confirm"}, status=400)
    if action == "restart-desktop":
        subprocess.Popen(["supervisorctl", "restart", "desktop"],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return web.json_response({"status": "restarting-desktop"})
    if action == "reboot":
        def _shutdown():
            try:
                if os.environ.get("AUTO_BACKUP_ON_EXIT", "1") == "1":
                    subprocess.run(["/usr/local/bin/backup-data"],
                                   timeout=120)
            except Exception:
                pass
            time.sleep(1)
            subprocess.run(["supervisorctl", "shutdown"], timeout=20)
        threading.Thread(target=_shutdown, daemon=True).start()
        return web.json_response({"status": "rebooting"})
    return web.json_response({"status": "error",
                              "msg": "unknown action"}, status=404)


# ---------------------------------------------------------------- routing

@web.middleware
async def error_middleware(request, handler):
    """Last-resort guard: a buggy handler must never take the server down
    nor leak internals to the client. Full traceback goes to stderr
    (/dev/stderr -> Railway deploy logs); client gets a clean JSON 500.
    """
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("unhandled error on %s %s",
                      request.method, request.path_qs)
        return web.json_response(
            {"status": "error", "msg": "internal error"}, status=500)


app = web.Application(middlewares=[error_middleware],
                      client_max_size=8 * 1024 * 1024)
app.on_startup.append(on_startup)
app.on_cleanup.append(cleanup)
app.router.add_get("/", handle_index)
app.router.add_get("/health", handle_health)
app.router.add_get("/api/stats", handle_stats)
app.router.add_get("/api/session", handle_session)
app.router.add_get("/api/vnc/client", vnc_client_info)
app.router.add_get("/api/services", handle_services)
app.router.add_post("/api/start/code-server", start_code_server)
app.router.add_get("/api/start/code-server", start_code_server)
app.router.add_post("/api/apps/{name}", launch_app)
app.router.add_get("/api/logs/list", logs_list)
app.router.add_get("/api/logs/view/{name}", logs_view)
app.router.add_post("/api/logs/clear/{name}", logs_clear)
app.router.add_post("/api/optimize/run", optimize_run)
app.router.add_get("/api/optimize/status", optimize_status)
app.router.add_get("/api/optimize/stream", optimize_stream)
app.router.add_get("/api/wallpaper/list", wallpaper_list)
app.router.add_post("/api/wallpaper/preset", wallpaper_preset)
app.router.add_post("/api/wallpaper/upload", wallpaper_upload)
app.router.add_post("/api/system/{action}", system_power)
app.router.add_get("/api/tasks/status", tasks_status)
app.router.add_post("/api/tasks/run/{task}", tasks_run)
app.router.add_get("/api/tasks/stream", tasks_stream)
app.router.add_get("/api/os/profiles", os_profiles)
app.router.add_get("/api/ai/status", ai_status)
app.router.add_post("/api/ai/chat", ai_chat_handler)
app.router.add_post("/api/ai/exec", ai_exec)
app.router.add_route("*", "/code", code_proxy)
app.router.add_route("*", "/code/{path:.*}", code_proxy)
app.router.add_get("/novnc/{path:.*}", handle_novnc)
app.router.add_get("/websockify", vnc_ws_handler)

# Catch-all serves the same noVNC static tree (same safe_join guard).
app.router.add_get("/{path:.*}", handle_novnc)


def main():
    if PORT in (VNC_PORT, CODE_PORT):
        # Defense in depth for start.sh's reserved-port guard: binding on
        # Xvnc's or code-server's port can only end in 'address already in
        # use' crash-loops - refuse loudly instead.
        log.critical(
            "PORT=%d collides with an internal service (Xvnc=%d, "
            "code-server=%d). Remove/override the PORT env var "
            "(Railway Variables) and redeploy.", PORT, VNC_PORT, CODE_PORT)
        raise SystemExit(1)
    log.info("Starting HTTP server on 0.0.0.0:%s (py=%s aiohttp=%s)",
             PORT, sys.version.split()[0],
             getattr(aiohttp, "__version__", "?"))
    try:
        # access_log=None: stats are polled every ~2s per client; logging
        # each poll only spams Railway deploy logs with no diagnostic value.
        web.run_app(app, host="0.0.0.0", port=PORT, access_log=None)
    except Exception:
        # ALWAYS print the full traceback to stderr (/dev/stderr -> Railway
        # deploy logs) before a non-zero exit, so a crash is diagnosable
        # from supervisord output alone.
        traceback.print_exc()
        sys.stderr.flush()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
