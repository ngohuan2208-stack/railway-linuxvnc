#!/usr/bin/env python3
"""HTTP server: noVNC proxy, stats API, static files."""
import asyncio
import logging
import os
import subprocess
import sys
import time

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
NOVNC_DIR = "/usr/share/novnc"
STATIC_DIR = "/srv"

stats_cache = {"data": None, "ts": 0}


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
        with open("/proc/net/wireless") as f:
            lines = f.readlines()
            if len(lines) > 2:
                iw = os.popen("iw dev wlan0 link 2>/dev/null").read()
                for line in iw.splitlines():
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
            fps = int(os.environ.get("VNC_FPS", "30"))
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


async def handle_stats(request):
    return web.json_response(collect_stats())


async def handle_health(request):
    return web.Response(text="ok", status=200)


async def handle_novnc(request):
    rel = request.match_info.get("path", "")
    fpath = os.path.join(NOVNC_DIR, rel)
    if os.path.isfile(fpath):
        return web.FileResponse(fpath)
    return web.Response(status=404)


async def ws_handler(request):
    ws_server = web.WebSocketResponse()
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
app.router.add_get("/", handle_index)
app.router.add_get("/health", handle_health)
app.router.add_get("/api/stats", handle_stats)
app.router.add_get("/novnc/{path:.*}", handle_novnc)
app.router.add_get("/websockify", ws_handler)
app.router.add_get("/{path:.*}", handle_static)


def main():
    port = int(os.environ.get("PORT", "8080"))
    log.info("Starting HTTP server on port %s", port)
    log.info("Serving noVNC from %s", NOVNC_DIR)
    log.info("Serving index from %s", STATIC_DIR)
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
