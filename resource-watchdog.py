#!/usr/bin/env python3
"""Resource watchdog: RAM budget, CPU cap, disk auto-clean + service revival.

Service revival policy (no infinite restart loops):
- A service is considered DOWN only after N consecutive failed checks.
- Restart attempts use exponential backoff: 30s * 2^fails, capped at 600s.
- Max 6 restart attempts per rolling hour per service; beyond that it logs
  an ERROR and waits for the window to slide.

Optimized for performance and multi-user support.
"""
import os
import subprocess
import time
from collections import deque

import psutil

MEM_LIMIT_MB = int(os.environ.get("MEM_LIMIT_MB", "1228"))
CPU_MAX_PCT = int(os.environ.get("CPU_MAX_PCT", "85"))
DISK_CLEAN_PCT = int(os.environ.get("DISK_CLEAN_PCT", "80"))
CHECK_INTERVAL = int(os.environ.get("WATCHDOG_INTERVAL", "5"))
MAX_VNC_CONNECTIONS = int(os.environ.get("MAX_VNC_CONNECTIONS", "3"))

FAIL_THRESHOLD = 2
BACKOFF_BASE = 30
BACKOFF_CAP = 600
MAX_ATTEMPTS_PER_HOUR = 6

PROTECTED = {
    "supervisord", "Xvnc", "dbus-daemon", "dbus-launch",
    "http-server.py", "resource-watchdog.py", "idle-monitor.py",
    "systemd", "bash", "sh", "su", "sudo", "python3", "init",
}
HEAVY_APPS = {
    "chromium", "chromium-browser", "firefox-esr", "firefox",
    "code-server", "soffice.bin", "gimp-2.10", "vlc", "onboard",
    "xfce4-terminal", "code",
}

cpu_high_since = 0
last_connections_check = 0
connections_check_interval = 30  # Check connections every 30 seconds


def log(msg):
    print(f"[watchdog] {msg}", flush=True)


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


def drop_caches():
    try:
        subprocess.run(["sync"], timeout=5)
        with open("/proc/sys/vm/drop_caches", "w") as f:
            f.write("3\n")
    except Exception:
        pass


def proc_name(p):
    try:
        return p.info["name"]
    except Exception:
        return ""


def renice(pid, nice):
    try:
        os.setpriority(os.PRIO_PROCESS, pid, nice)
    except Exception:
        pass


def top_by_rss(exclude_protected=True):
    procs = []
    for p in psutil.process_iter(["name", "memory_info", "pid"]):
        n = proc_name(p)
        if exclude_protected and (n in PROTECTED or n.startswith("python")):
            continue
        mi = p.info.get("memory_info")
        if mi and mi.rss > 40 * 1024 * 1024:
            procs.append((mi.rss, p.info["pid"], n))
    procs.sort(reverse=True)
    return procs


def handle_memory():
    """Manage memory usage with multi-user awareness."""
    cg_used, cg_limit = cgroup_mem()
    if cg_used is not None:
        used_mb = cg_used // (1024 * 1024)
        budget_mb = (cg_limit // (1024 * 1024)) if cg_limit else MEM_LIMIT_MB
    else:
        mem = psutil.virtual_memory()
        used_mb = mem.used // (1024 * 1024)
        budget_mb = MEM_LIMIT_MB
    pct_of_budget = used_mb / budget_mb * 100

    # Adjust thresholds based on number of VNC connections
    # More connections = more aggressive memory management
    connection_factor = 1.0
    try:
        with open("/proc/net/tcp", "r") as f:
            # Count VNC connections (port 5901 = 0x170D)
            vnc_conns = sum(1 for line in f.readlines()[1:] 
                          if "170D" in line.split()[1] if len(line.split()) > 1)
            if vnc_conns > 1:
                connection_factor = 1.0 + (vnc_conns - 1) * 0.1  # 10% more aggressive per extra connection
    except Exception:
        pass

    # Apply connection-aware thresholds
    critical_threshold = 95 / connection_factor
    high_threshold = 82 / connection_factor
    medium_threshold = 70 / connection_factor

    if pct_of_budget >= critical_threshold:
        log(f"CRITICAL {used_mb}MB/{budget_mb}MB (threshold={critical_threshold:.0f}%) - killing heaviest app")
        for rss, pid, name in top_by_rss():
            if name in HEAVY_APPS:
                try:
                    psutil.Process(pid).terminate()
                    log(f"killed {name}(pid={pid}) freed~{rss//1048576}MB")
                except Exception:
                    pass
                break
        drop_caches()

    elif pct_of_budget >= high_threshold:
        drop_caches()
        for _, pid, _ in top_by_rss()[:4]:
            renice(pid, 15)

    elif pct_of_budget >= medium_threshold:
        for _, pid, _ in top_by_rss()[:2]:
            renice(pid, 10)


def handle_cpu(avg):
    global cpu_high_since
    now = time.time()
    if avg >= CPU_MAX_PCT:
        if cpu_high_since == 0:
            cpu_high_since = now
            return
        if now - cpu_high_since >= CHECK_INTERVAL * 2:
            best = None
            for p in psutil.process_iter(["name", "cpu_percent", "pid"]):
                n = proc_name(p)
                if n in PROTECTED or n.startswith("python"):
                    continue
                cpu = p.info.get("cpu_percent") or 0
                if best is None or cpu > best[0]:
                    best = (cpu, p.info["pid"], n)
            if best and best[0] > 15:
                log(f"CPU {avg:.0f}% sustained - renice {best[2]}(pid={best[1]})")
                renice(best[1], 19)
            cpu_high_since = now
    else:
        cpu_high_since = 0


def clean_disk():
    targets = [
        "/home/user/.cache/*",
        "/home/user/.config/chromium/*/Cache/*",
        "/home/user/.config/chromium/*/Code Cache/*",
        "/home/user/.mozilla/*/*.default*/cache2/*",
        "/var/cache/apt/archives/*.deb",
        "/tmp/*.tar.gz",
    ]
    freed_before = psutil.disk_usage("/").used
    for t in targets:
        subprocess.run(["sh", "-c", f"rm -rf {t} 2>/dev/null"], timeout=30)
    freed = (freed_before - psutil.disk_usage("/").used) // (1024 * 1024)
    log(f"disk cleaned, freed ~{freed}MB")


def handle_disk():
    d = psutil.disk_usage("/")
    if d.percent >= DISK_CLEAN_PCT:
        log(f"disk {d.percent:.0f}% >= {DISK_CLEAN_PCT}% - cleaning")
        clean_disk()


# ------------------------------------------------------------ svc revival

def listening(port):
    """Check LISTEN state via /proc/net/tcp - no TCP connection is opened.

    Raw connect+close probes would trip Xvnc's failure blacklist and can
    lock out real noVNC clients ('Too many security failures').
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


def proc_alive(name):
    for p in psutil.process_iter(["name"]):
        if proc_name(p) == name:
            return True
    return False


def desktop_session_proc():
    """Process name of the running desktop session (DESKTOP env)."""
    return {"xfce": "xfce4-session", "lxqt": "lxqt-session"}.get(
        os.environ.get("DESKTOP", "lxqt"), "lxqt-session")


SERVICES = [
    # key, supervisor name, healthy check, log tag
    {"key": "vnc", "supervisor": "xvnc",
     "check": lambda: listening(5901), "tag": "VNC"},
    {"key": "desktop", "supervisor": "desktop",
     "check": lambda: proc_alive(desktop_session_proc()), "tag": "DESKTOP"},
    {"key": "httpserver", "supervisor": "httpserver",
     "check": lambda: listening(int(os.environ.get("PORT", "8080"))),
     "tag": "HTTP"},
]

svc_state = {s["key"]: {"fails": 0, "attempts": deque(),
                        "last_attempt": 0} for s in SERVICES}


def supervisor_action(name, action):
    try:
        r = subprocess.run(
            ["supervisorctl", action, name],
            capture_output=True, text=True, timeout=20,
        )
        log(f"supervisorctl {action} {name}: "
            f"{(r.stdout or r.stderr).strip()[:120]}")
        return r.returncode == 0
    except Exception as e:
        log(f"supervisorctl {action} {name} error: {type(e).__name__}")
        return False


def revive_services():
    now = time.time()
    for svc in SERVICES:
        st = svc_state[svc["key"]]
        if svc["check"]():
            if st["fails"] >= FAIL_THRESHOLD:
                log(f"[{svc['tag']}] ready (recovered)")
            st["fails"] = 0
            continue

        st["fails"] += 1
        if st["fails"] == FAIL_THRESHOLD:
            log(f"[{svc['tag']}] unhealthy ({st['fails']} failed checks)")
        if st["fails"] < FAIL_THRESHOLD:
            continue

        backoff = min(BACKOFF_BASE * (2 ** (st["fails"] - FAIL_THRESHOLD)),
                      BACKOFF_CAP)
        if now - st["last_attempt"] < backoff:
            continue

        # rolling-hour attempt limiter
        while st["attempts"] and now - st["attempts"][0] > 3600:
            st["attempts"].popleft()
        if len(st["attempts"]) >= MAX_ATTEMPTS_PER_HOUR:
            if now - st["last_attempt"] > 600:
                log(f"[ERROR] [{svc['tag']}] restart limit hit "
                    f"({len(st['attempts'])}/hour), giving up this window")
                st["last_attempt"] = now
            continue

        log(f"[{svc['tag']}] restarting via supervisord "
            f"(attempt {len(st['attempts']) + 1})")
        st["attempts"].append(now)
        st["last_attempt"] = now
        supervisor_action(svc["supervisor"], "restart")


def check_vnc_connections():
    """Monitor VNC connections and optimize resources based on usage."""
    global last_connections_check
    now = time.time()
    
    if now - last_connections_check < connections_check_interval:
        return
    
    last_connections_check = now
    
    try:
        # Count active VNC connections
        vnc_conns = 0
        with open("/proc/net/tcp", "r") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) > 1:
                    local_port = parts[1].split(":")[1] if ":" in parts[1] else ""
                    if local_port == "170D":  # 5901 in hex
                        vnc_conns += 1
        
        if vnc_conns > 0:
            log(f"Active VNC connections: {vnc_conns}/{MAX_VNC_CONNECTIONS}")
            
            # If we have many connections, be more aggressive with memory
            if vnc_conns >= MAX_VNC_CONNECTIONS:
                log(f"High connection count ({vnc_conns}) - increasing memory pressure")
                drop_caches()
    except Exception as e:
        log(f"VNC connection check error: {e}")


def main():
    log(f"started | mem={MEM_LIMIT_MB}MB cpu<={CPU_MAX_PCT}% "
        f"disk<{DISK_CLEAN_PCT}% interval={CHECK_INTERVAL}s "
        f"max_connections={MAX_VNC_CONNECTIONS}")
    while True:
        time.sleep(CHECK_INTERVAL)
        try:
            revive_services()
            handle_memory()
            avg = psutil.cpu_percent(interval=0.5)
            handle_cpu(avg)
            handle_disk()
            check_vnc_connections()
        except Exception as e:
            log(f"error: {e}")


if __name__ == "__main__":
    main()
