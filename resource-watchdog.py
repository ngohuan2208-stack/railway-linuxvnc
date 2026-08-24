#!/usr/bin/env python3
"""Resource watchdog: RAM <= budget, CPU cap, disk auto-clean."""
import os
import subprocess
import time

import psutil

MEM_LIMIT_MB = int(os.environ.get("MEM_LIMIT_MB", "1228"))
CPU_MAX_PCT = int(os.environ.get("CPU_MAX_PCT", "85"))
DISK_CLEAN_PCT = int(os.environ.get("DISK_CLEAN_PCT", "80"))
CHECK_INTERVAL = int(os.environ.get("WATCHDOG_INTERVAL", "10"))

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


def log(msg):
    print(f"[watchdog] {msg}", flush=True)


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
    mem = psutil.virtual_memory()
    used_mb = mem.used // (1024 * 1024)
    pct_of_budget = used_mb / MEM_LIMIT_MB * 100

    if pct_of_budget >= 95:
        log(f"CRITICAL {used_mb}MB/{MEM_LIMIT_MB}MB — killing heaviest app")
        for rss, pid, name in top_by_rss():
            if name in HEAVY_APPS:
                try:
                    psutil.Process(pid).terminate()
                    log(f"killed {name}(pid={pid}) freed~{rss//1048576}MB")
                except Exception:
                    pass
                break
        drop_caches()

    elif pct_of_budget >= 82:
        drop_caches()
        for _, pid, _ in top_by_rss()[:4]:
            renice(pid, 15)

    elif pct_of_budget >= 70:
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
                log(f"CPU {avg:.0f}% sustained — renice {best[2]}(pid={best[1]})")
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
        log(f"disk {d.percent:.0f}% >= {DISK_CLEAN_PCT}% — cleaning")
        clean_disk()


def main():
    log(f"started | mem={MEM_LIMIT_MB}MB cpu<={CPU_MAX_PCT}% disk<{DISK_CLEAN_PCT}%")
    while True:
        time.sleep(CHECK_INTERVAL)
        try:
            handle_memory()
            avg = psutil.cpu_percent(interval=0.5)
            handle_cpu(avg)
            handle_disk()
        except Exception as e:
            log(f"error: {e}")


if __name__ == "__main__":
    main()
