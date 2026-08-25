#!/usr/bin/env python3
"""Idle monitor: OPTIONAL desktop suspend to save RAM.

24/7 mode (default): IDLE_TIMEOUT=0 -> the desktop is NEVER suspended.
The process stays alive with a tiny footprint so supervisord does not
restart-loop, and so enabling the feature at runtime stays possible via
env var + redeploy.

Opt-in: set IDLE_TIMEOUT=<seconds> to re-enable suspend-on-idle.
"""
import os
import signal
import subprocess
import sys
import time

IDLE_TIMEOUT = int(os.environ.get("IDLE_TIMEOUT", "0"))
IDLE_CHECK = int(os.environ.get("IDLE_CHECK", "10"))
DROP_CACHE = os.environ.get("DROP_CACHE", "1") == "1"
SUSPEND_FILE = "/tmp/desktop_suspended"
XPRINTIDLE = "/usr/bin/xprintidle"
DISPLAY = os.environ.get("DISPLAY", ":1")

ENABLED = IDLE_TIMEOUT > 0


def log(msg):
    print(f"[idle-monitor] {msg}", flush=True)


def get_idle_ms():
    try:
        out = subprocess.check_output(
            [XPRINTIDLE], env={"DISPLAY": DISPLAY}, timeout=5
        )
        return int(out.strip())
    except Exception:
        return 0


def is_suspended():
    return os.path.exists(SUSPEND_FILE)


def drop_caches():
    try:
        with open("/proc/sys/vm/drop_caches", "w") as f:
            f.write("3\n")
        log("dropped page caches")
    except Exception as e:
        log(f"drop_caches failed: {e}")


def suspend_desktop():
    if not ENABLED or is_suspended():
        return
    log(f"suspending desktop (idle > {IDLE_TIMEOUT}s)")

    try:
        subprocess.run(
            ["supervisorctl", "stop", "desktop"],
            timeout=10, capture_output=True,
        )
    except Exception as e:
        log(f"stop desktop: {e}")

    if DROP_CACHE:
        drop_caches()

    try:
        with open(SUSPEND_FILE, "w") as f:
            f.write(str(int(time.time())))
    except Exception:
        pass

    log("desktop suspended")


def resume_desktop():
    if not is_suspended():
        return
    log("resuming desktop")

    try:
        subprocess.run(
            ["supervisorctl", "start", "desktop"],
            timeout=10, capture_output=True,
        )
    except Exception as e:
        log(f"start desktop: {e}")

    try:
        os.remove(SUSPEND_FILE)
    except Exception:
        pass

    log("desktop resumed")


def handle_signal(sig, frame):
    log(f"signal {sig}, resuming...")
    resume_desktop()
    sys.exit(0)


def main():
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    if not ENABLED:
        # clear any stale suspend marker from previous runs
        resume_desktop()
        log("disabled (IDLE_TIMEOUT=0) - desktop runs 24/7")
        # sleep forever with negligible footprint; keeps supervisor state
        # RUNNING and avoids restart churn
        while True:
            time.sleep(3600)

    log(f"started | timeout={IDLE_TIMEOUT}s | check={IDLE_CHECK}s "
        f"| cache={DROP_CACHE}")

    while True:
        time.sleep(IDLE_CHECK)

        idle = get_idle_ms()
        idle_s = idle / 1000

        if idle_s > IDLE_TIMEOUT and not is_suspended():
            suspend_desktop()
        elif idle_s < 5 and is_suspended():
            resume_desktop()


if __name__ == "__main__":
    main()
