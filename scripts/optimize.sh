#!/bin/bash
# ============================================================
# Railway System Optimizer
# Safe cleanup + tuning. NEVER touches user data.
#
# Protected (never deleted):
#   /home/user/{Desktop,Documents,Downloads,Projects,Drive,.ssh,.gitconfig}
#   /home/user/.backups, source code, SSH keys, git config
#
# Only cleans:
#   apt cache, package lists, /var/tmp, old /tmp files (>1h),
#   rotated logs (*.gz *.1 *.old), browser caches (Cache dirs only),
#   thumbnails, ~/.cache
#
# Usage:
#   optimize-system            real run
#   optimize-system --dry-run  preview only
# Exit codes: 0=ok 1=some steps failed 2=precheck failed
# Log:        /var/log/optimizer.log
# ============================================================
set -u

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

LOG_FILE="/var/log/optimizer.log"
STEP_TOTAL=9
STEP=0
ERRORS=0
START_TS=$(date +%s)

RAM_BEFORE_KB=$(awk '/MemAvailable/{print $2}' /proc/meminfo 2>/dev/null || echo 0)
DISK_BEFORE_USED_KB=$(df -k / 2>/dev/null | awk 'NR==2{print $3}')
DISK_BEFORE_AVAIL_KB=$(df -k / 2>/dev/null | awk 'NR==2{print $4}')

log() {
    local line
    line="$(date '+%Y-%m-%d %H:%M:%S') $*"
    echo "$line" | tee -a "$LOG_FILE"
}

step() {
    STEP=$((STEP + 1))
    log ""
    log "[${STEP}/${STEP_TOTAL}] $*"
}

ok()   { log "  OK: $*"; }
warn() { log "  WARN: $*"; }
fail() { ERRORS=$((ERRORS + 1)); log "  FAIL: $*"; }

run_or_dry() {
    # run_or_dry <description> <command...>
    local desc="$1"; shift
    if [ "$DRY_RUN" = "1" ]; then
        log "  [DRY-RUN] would run: $desc"
    else
        if "$@" >/dev/null 2>&1; then
            ok "$desc"
        else
            fail "$desc"
        fi
    fi
}

du_kb() { du -sk "$1" 2>/dev/null | awk '{print $1}'; }

# ------------------------------------------------ prechecks
if [ "$(id -u)" != "0" ]; then
    log "[OPTIMIZER] ERROR: must run as root"
    exit 2
fi
if [ ! -f /etc/os-release ] || [ ! -d /proc ] || [ ! -x /bin/df ]; then
    log "[OPTIMIZER] ERROR: unsupported environment"
    exit 2
fi
mkdir -p /var/log
touch "$LOG_FILE" 2>/dev/null || LOG_FILE=/tmp/optimizer-fallback.log

log "====================================================="
log "[OPTIMIZER] started mode=$([ $DRY_RUN = 1 ] && echo DRY-RUN || echo APPLY)"

# ------------------------------------------------ [1/9] CPU
step "Checking CPU"
CPU_CORES=$(nproc 2>/dev/null || echo 1)
LOAD=$(cut -d' ' -f1 /proc/loadavg 2>/dev/null || echo 0)
ok "cores=${CPU_CORES} load1=${LOAD}"

# ------------------------------------------------ [2/9] RAM
step "Checking RAM"
MEM_TOTAL_KB=$(awk '/MemTotal/{print $2}' /proc/meminfo 2>/dev/null || echo 0)
MEM_AVAIL_KB=$(awk '/MemAvailable/{print $2}' /proc/meminfo 2>/dev/null || echo 0)
if [ -f /sys/fs/cgroup/memory.max ]; then
    CG_LIMIT=$(cat /sys/fs/cgroup/memory.max)
elif [ -f /sys/fs/cgroup/memory/memory.limit_in_bytes ]; then
    CG_LIMIT=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes)
else
    CG_LIMIT=""
fi
CG_USED=$(cat /sys/fs/cgroup/memory.current 2>/dev/null \
    || cat /sys/fs/cgroup/memory/memory.usage_in_bytes 2>/dev/null || echo 0)
ok "ram total=$((MEM_TOTAL_KB / 1024))MB avail=$((MEM_AVAIL_KB / 1024))MB"
[ -n "$CG_LIMIT" ] && [ "$CG_LIMIT" != "max" ] \
    && ok "cgroup limit=$((CG_LIMIT / 1048576))MB used=$((CG_USED / 1048576))MB"

# ------------------------------------------------ [3/9] Disk
step "Checking disk"
DISK_PCT=$(df -P / | awk 'NR==2{gsub(/%/,""); print $5}')
ok "root usage=${DISK_PCT}%"
[ "${DISK_PCT:-0}" -ge 90 ] && warn "disk usage high (${DISK_PCT}%)"

# ------------------------------------------------ [4/9] Package cache
step "Cleaning package cache"
APT_CACHE_KB=$(du_kb /var/cache/apt/archives 2>/dev/null || echo 0)
run_or_dry "apt-get clean" apt-get clean
if [ "$DRY_RUN" != "1" ]; then
    rm -rf /var/lib/apt/lists/* 2>/dev/null && ok "cleared apt lists" \
        || fail "clear apt lists"
else
    log "  [DRY-RUN] would clear /var/lib/apt/lists/*"
fi
APT_FREED_MB=$((APT_CACHE_KB / 1024))
ok "package cache freed ~${APT_FREED_MB}MB"

# ------------------------------------------------ [5/9] Temporary files
step "Cleaning temporary files"
TMP_BEFORE_KB=$(du_kb /tmp 2>/dev/null || echo 0)
VAR_TMP_KB=$(du_kb /var/tmp 2>/dev/null || echo 0)
OLD_LOGS_KB=0
for f in /var/log/*.gz /var/log/*.1 /var/log/*.old /var/log/supervisor/*.gz \
         /var/log/supervisor/*.1; do
    [ -f "$f" ] && OLD_LOGS_KB=$((OLD_LOGS_KB + $(du_kb "$f")))
done
if [ "$DRY_RUN" = "1" ]; then
    log "  [DRY-RUN] would delete /tmp files older than 60 min (excluding X11 sockets)"
    log "  [DRY-RUN] would empty /var/tmp/*"
    log "  [DRY-RUN] would delete ${OLD_LOGS_KB}KB of rotated logs"
else
    find /tmp -mindepth 1 -maxdepth 1 -mmin +60 \
        ! -name '.X11-unix' ! -name '.ICE-unix' ! -name '.font-unix' \
        ! -name '.XIM-unix' ! -name '.Test-unix' \
        -exec rm -rf {} + 2>/dev/null && ok "cleaned old /tmp files" \
        || warn "partial /tmp cleanup"
    rm -rf /var/tmp/* 2>/dev/null && ok "emptied /var/tmp" || warn "/var/tmp partial"
    rm -f /var/log/*.gz /var/log/*.1 /var/log/*.old \
          /var/log/supervisor/*.gz /var/log/supervisor/*.1 2>/dev/null \
        && ok "removed rotated logs (~$((OLD_LOGS_KB / 1024))MB)" || true
fi

# ------------------------------------------------ [6/9] XFCE
step "Optimizing XFCE"
XFCE_TWEAKS=0
if command -v xfconf-query >/dev/null 2>&1; then
    for prop_val in \
        "/general/use_compositing false" \
        "/general/show_frame_shadow false"; do
        prop="${prop_val% *}"; val="${prop_val#* }"
        if [ "$DRY_RUN" = "1" ]; then
            log "  [DRY-RUN] would set xfwm4 ${prop}=${val}"
        else
            if DISPLAY=:1 timeout 5 xfconf-query -c xfwm4 -p "$prop" \
                -t bool -s "$val" --create -n >/dev/null 2>&1; then
                XFCE_TWEAKS=$((XFCE_TWEAKS + 1))
            fi
        fi
    done
    [ "$DRY_RUN" != "1" ] && ok "xfwm4 tweaks applied (${XFCE_TWEAKS})"
else
    warn "xfconf-query not available (compositor already off via config)"
fi

# ------------------------------------------------ [7/9] Browser caches
step "Optimizing browser cache"
BR_BEFORE_KB=0
for d in /home/user/.config/chromium/*/Cache \
         /home/user/.config/chromium/*/Code\ Cache \
         /home/user/.config/chromium/*/GPUCache \
         /home/user/.mozilla/*/*/cache2 \
         /home/user/.cache/mozilla; do
    [ -d "$d" ] && BR_BEFORE_KB=$((BR_BEFORE_KB + $(du_kb "$d")))
done
BR_CACHE_KB=$(du_kb /home/user/.cache 2>/dev/null || echo 0)
if [ "$DRY_RUN" = "1" ]; then
    log "  [DRY-RUN] would clean browser caches (~$((BR_BEFORE_KB / 1024))MB) + ~/.cache (~$((BR_CACHE_KB / 1024))MB)"
    log "  [DRY-RUN] passwords/history/bookmarks are NOT touched"
else
    rm -rf /home/user/.config/chromium/*/Cache \
           /home/user/.config/chromium/*/Code\ Cache \
           /home/user/.config/chromium/*/GPUCache 2>/dev/null
    rm -rf /home/user/.mozilla/*/*/cache2 /home/user/.cache/mozilla 2>/dev/null
    rm -rf /home/user/.cache/thumbnails 2>/dev/null
    rm -rf /home/user/.cache/* 2>/dev/null
    ok "browser+user cache cleaned (~$(( (BR_BEFORE_KB + BR_CACHE_KB) / 1024 ))MB), user data untouched"
fi

# ------------------------------------------------ [8/9] Services check
step "Checking services"
SERVICES_OK=0
SERVICES_TOTAL=0
check_one() {
    local label="$1"; shift
    SERVICES_TOTAL=$((SERVICES_TOTAL + 1))
    if "$@" >/dev/null 2>&1; then
        SERVICES_OK=$((SERVICES_OK + 1)); ok "$label"
    else
        fail "$label NOT RUNNING"
    fi
}
check_one "Xvnc(5901) running" bash -c 'exec 3<>/dev/tcp/127.0.0.1/5901'
pgrep -x xfce4-session >/dev/null && SERVICES_TOTAL=$((SERVICES_TOTAL+1)) \
    && { SERVICES_OK=$((SERVICES_OK+1)); ok "XFCE session"; } \
    || { SERVICES_TOTAL=$((SERVICES_TOTAL+1)); fail "XFCE session"; }
PORT_SVC="${PORT:-8080}"
check_one "HTTP(${PORT_SVC}) running" bash -c "exec 3<>/dev/tcp/127.0.0.1/${PORT_SVC}"

# ------------------------------------------------ [9/9] Railway opts
step "Applying Railway optimizations"
sync 2>/dev/null && ok "sync done" || true
if [ "$DRY_RUN" = "1" ]; then
    log "  [DRY-RUN] would attempt kernel drop_caches (may be denied in container)"
else
    sync
    if echo 3 > /proc/sys/vm/drop_caches 2>/dev/null; then
        ok "kernel page cache dropped"
    else
        warn "drop_caches denied by container runtime (normal on Railway)"
    fi
fi

# ------------------------------------------------ summary
sleep 1
RAM_AFTER_KB=$(awk '/MemAvailable/{print $2}' /proc/meminfo 2>/dev/null || echo 0)
DISK_AFTER_USED_KB=$(df -k / 2>/dev/null | awk 'NR==2{print $3}')

RAM_SAVED_MB=$(( (RAM_AFTER_KB - RAM_BEFORE_KB) / 1024 ))
[ "$RAM_SAVED_MB" -lt 0 ] && RAM_SAVED_MB=0
DISK_CLEANED_MB=$(( (DISK_BEFORE_USED_KB - DISK_AFTER_USED_KB) / 1024 ))
[ "$DISK_CLEANED_MB" -lt 0 ] && DISK_CLEANED_MB=0
END_TS=$(date +%s)
DURATION=$((END_TS - START_TS))
STEPS_OK=$((STEP_TOTAL - ERRORS))

log ""
log "[OPTIMIZER] completed dry_run=${DRY_RUN}"
RESULT_JSON="{\"dry_run\":${DRY_RUN},\"ram_saved_mb\":${RAM_SAVED_MB},\"disk_cleaned_mb\":${DISK_CLEANED_MB},\"steps_ok\":${STEPS_OK},\"steps_total\":${STEP_TOTAL},\"errors\":${ERRORS},\"services_ok\":${SERVICES_OK},\"services_total\":${SERVICES_TOTAL},\"duration_s\":${DURATION}}"
echo "OPT_RESULT_JSON:${RESULT_JSON}" | tee -a "$LOG_FILE"

[ "$ERRORS" -gt 0 ] && exit 1 || exit 0
