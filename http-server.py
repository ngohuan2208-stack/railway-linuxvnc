#!/usr/bin/env python3
import asyncio
import json
import os
import time
from pathlib import Path

import psutil
from aiohttp import web

VNC_HOST = "127.0.0.1"
VNC_PORT = 5901
NOVNC_DIR = "/usr/share/novnc"
STATIC_DIR = "/srv"

stats_cache = {"data": None, "ts": 0}


def collect_stats():
    now = time.time()
    if stats_cache["data"] and (now - stats_cache["ts"]) < 1.5:
        return stats_cache["data"]

    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    cpu_freq = psutil.cpu_freq()
    net = psutil.net_io_counters()
    load = os.getloadavg()
    uptime_s = time.time() - psutil.boot_time()

    days = int(uptime_s // 86400)
    hours = int((uptime_s % 86400) // 3600)
    mins = int((uptime_s % 3600) // 60)

    try:
        with open("/proc/net/wireless") as f:
            lines = f.readlines()
            wifi = len(lines) > 2
    except Exception:
        wifi = False

    wifi_info = None
    if wifi:
        try:
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

    procs = len(psutil.pids())

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
        "processes": procs,
        "timestamp": int(now),
    }
    stats_cache["data"] = stats
    stats_cache["ts"] = now
    return stats


def fmt_bytes(b):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


async def handle_stats(request):
    return web.json_response(collect_stats())


async def handle_index(request):
    return web.FileResponse(os.path.join(STATIC_DIR, "index.html"))


async def handle_static(request):
    rel = request.match_info.get("path", "")
    fpath = os.path.join(NOVNC_DIR, rel)
    if os.path.isfile(fpath):
        return web.FileResponse(fpath)
    return web.Response(status=404)


async def handle_novnc_static(request):
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


app = web.Application()
app.router.add_get("/", handle_index)
app.router.add_get("/api/stats", handle_stats)
app.router.add_get("/novnc/{path:.*}", handle_novnc_static)
app.router.add_get("/websockify", ws_handler)
app.router.add_get("/{path:.*}", handle_static)


def main():
    port = int(os.environ.get("HTTP_PORT", "8080"))
    print(f"HTTP server on port {port}")
    web.run_app(app, host="0.0.0.0", port=port, print=None)


if __name__ == "__main__":
    main()
