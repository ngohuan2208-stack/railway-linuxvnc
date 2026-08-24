#!/usr/bin/env python3
"""HTTP server: noVNC proxy, code-server proxy, stats API, static files."""
import asyncio
import logging
import os
import subprocess
import sys
import time

import aiohttp
import psutil
from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="[http-server] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

VNC_HOST = "127.0.0.1"
VNC_PORT = 5901
CODE_HOST = "127.0.0.1"
CODE_PORT = 8443
NOVNC_DIR = "/usr/share/novnc"
STATIC_DIR = "/srv"

stats_cache = {"data": None, "ts": 0}
client_session: aiohttp.ClientSession = None

HOP_HEADERS = {
    "host", "connection", "upgrade", "keep-alive",
    "transfer-encoding", "content-encoding", "content-length",
}


async def on_startup(app):
    global client_session
    client_session = aiohttp.ClientSession()
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

    fps = 0
    try:
        xvnc_out = subprocess.check_output(
            ["pgrep", "-c", "Xvnc"], timeout=2
        ).decode().strip()
        if int(xvnc_out) > 0:
            fps = int(os.environ.get("VNC_FPS", "120"))
    except Exception:
        pass

    stats = {
        "cpu_percent": psutil.cpu_percent(interval=0),
        "cpu_count": psutil.cpu_count(),
        "cpu_freq": round(cpu_freq.current, 0) if cpu_freq else 0,
        "load_1": round(load[0], 2),
        "load_5": round(load[1], 2),
        "load_15": round(load[2], 2),
        "mem_total": mem.total,
        "mem_used": mem.used,
        "mem_percent": mem.percent,
        "mem_limit_mb": int(os.environ.get("MEM_LIMIT_MB", "1228")),
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
        "processes": len(psutil.pids()),
        "idle_ms": idle_ms,
        "suspended": suspended,
        "fps": fps,
        "timestamp": int(now),
    }
    stats_cache["data"] = stats
    stats_cache["ts"] = now
    return stats


async def handle_index(request):
    return web.FileResponse(os.path.join(STATIC_DIR, "index.html"))


async def handle_health(request):
    return web.Response(text="ok", status=200)


async def handle_stats(request):
    return web.json_response(collect_stats())


async def handle_novnc(request):
    rel = request.match_info.get("path", "")
    fpath = os.path.join(NOVNC_DIR, rel)
    if os.path.isfile(fpath):
        return web.FileResponse(fpath)
    return web.Response(status=404)


async def start_code_server(request):
    try:
        subprocess.Popen(
            ["supervisorctl", "start", "code-server"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return web.json_response({"status": "starting"})
    except Exception as e:
        return web.json_response({"status": "error", "msg": str(e)}, status=500)


def filter_headers(headers):
    return {k: v for k, v in headers.items() if k.lower() not in HOP_HEADERS}


async def code_ws_bridge(req, path):
    ws_server = web.WebSocketResponse(max_msg_size=16 * 1024 * 1024)
    await ws_server.prepare(req)

    qs = f"?{req.query_string}" if req.query_string else ""
    url = f"ws://{CODE_HOST}:{CODE_PORT}/{path}{qs}"
    try:
        session = aiohttp.ClientSession()
        ws_client = await session.ws_connect(url, max_msg_size=0)
    except Exception as e:
        log.warning("code-server WS connect failed: %s", e)
        await ws_server.close(code=1011)
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


async def vnc_ws_handler(request):
    ws_server = web.WebSocketResponse(max_msg_size=0)
    await ws_server.prepare(request)

    try:
        reader, writer = await asyncio.open_connection(VNC_HOST, VNC_PORT)
    except Exception as e:
        log.warning("VNC connect failed: %s", e)
        await ws_server.close(code=1011, message=str(e).encode())
        return ws_server

    async def client_to_vnc():
        try:
            async for msg in ws_server:
                if msg.type == web.WSMsgType.TEXT:
                    writer.write(msg.data.encode() if isinstance(msg.data, str) else msg.data)
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
                data = await reader.read(65536)
                if not data:
                    break
                await ws_server.send_bytes(data)
        except Exception:
            pass

    t1 = asyncio.create_task(client_to_vnc())
    t2 = asyncio.create_task(vnc_to_client())
    await asyncio.gather(t1, t2, return_exceptions=True)

    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass
    await ws_server.close()
    return ws_server


async def handle_static(request):
    rel = request.match_info.get("path", "")
    fpath = os.path.join(NOVNC_DIR, rel)
    if os.path.isfile(fpath):
        return web.FileResponse(fpath)
    return web.Response(status=404)


app = web.Application()
app.on_startup.append(on_startup)
app.on_cleanup.append(cleanup)
app.router.add_get("/", handle_index)
app.router.add_get("/health", handle_health)
app.router.add_get("/api/stats", handle_stats)
app.router.add_post("/api/start/code-server", start_code_server)
app.router.add_get("/api/start/code-server", start_code_server)
app.router.add_route("*", "/code", code_proxy)
app.router.add_route("*", "/code/{path:.*}", code_proxy)
app.router.add_get("/novnc/{path:.*}", handle_novnc)
app.router.add_get("/websockify", vnc_ws_handler)
app.router.add_get("/{path:.*}", handle_static)


def main():
    port = int(os.environ.get("PORT", "8080"))
    log.info("Starting HTTP server on port %s", port)
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
