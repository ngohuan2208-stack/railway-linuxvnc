#!/bin/bash
# ============================================================
# os-profile: "buff" he dieu hanh theo profile nguoi dung chon
#   lite    - sieu nhe: don dep + tinh chinh hieu nang (mac dinh neu skip)
#   dev     - developer day du (gcc, cmake, jq, ripgrep, fzf, tmux...)
#   media   - media & design (Inkscape, Krita, Audacity, mpv, HandBrake)
#   drivers - driver & phan cung (FUSE, NTFS/exFAT, USB/PCI, SMART...)
#   ultra   - BUFF TAT CA = dev + media + drivers
# Chay boi /api/tasks/run/os?profile=<name> - stream ra web terminal.
# Exit: 0 = OK, 2 = sai profile
# Log:  /var/log/os-profile.log
# ============================================================
set -u

PROFILE="${1:-lite}"
LOG_FILE="/var/log/os-profile.log"
STEP=0
ERRORS=0
START_TS=$(date +%s)
INSTALLED=0
MISSING=0

log() {
    local line
    line="$(date '+%H:%M:%S') $*"
    echo "$line" | tee -a "$LOG_FILE"
}

step() {
    STEP=$((STEP + 1))
    log ""
    log "[${STEP}/4] $*"
}

fail() { ERRORS=$((ERRORS + 1)); log "FAIL: $*"; }

finish() {
    local ok="$1"
    local dur=$(($(date +%s) - START_TS))
    log ""
    log "=== Xong (${dur}s) ==="
    echo "TASK_RESULT_JSON:{\"ok\":${ok},\"profile\":\"${PROFILE}\",\"packages_ok\":${INSTALLED},\"errors\":${ERRORS},\"duration_s\":${dur}}"
    exit 0
}

touch "$LOG_FILE" 2>/dev/null || LOG_FILE=/tmp/os-profile.log

PACK_DEV="build-essential cmake pkg-config manpages-dev strace lsof jq ripgrep fzf tmux sqlite3 python3-venv python3-pip net-tools dnsutils"
PACK_MEDIA="inkscape krita audacity mpv handbrake"
PACK_DRIVERS="fuse3 gvfs-backends gvfs-fuse udisks2 ntfs-3g exfat-fuse usbutils pciutils smartmontools lm-sensors cifs-utils"

case "$PROFILE" in
    lite)    PACKS="";;
    dev)     PACKS="$PACK_DEV";;
    media)   PACKS="$PACK_MEDIA";;
    drivers) PACKS="$PACK_DRIVERS";;
    ultra)   PACKS="$PACK_DEV $PACK_MEDIA $PACK_DRIVERS";;
    *)
        log "Sai profile: $PROFILE (lite|dev|media|drivers|ultra)"
        echo "TASK_RESULT_JSON:{\"ok\":false,\"profile\":\"$PROFILE\",\"reason\":\"unknown profile\",\"duration_s\":0}"
        exit 2
        ;;
esac

log "=== Buff he dieu hanh: ${PROFILE} ==="
if [ "$PROFILE" = "lite" ]; then
    log "(Lite = giu mac dinh LXQt nhe, don dep + tinh chinh, khong tai them gi)"
fi

export DEBIAN_FRONTEND=noninteractive

step "Cap nhat danh sach goi (apt-get update)"
if apt-get update >>"$LOG_FILE" 2>&1; then
    log "OK"
else
    fail "apt-get update - mang co the dang gap su co"
fi

step "Cai dat cac goi"
if [ -z "$PACKS" ]; then
    log "Khong co goi nao can tai."
else
    TOTAL=$(echo $PACKS | wc -w)
    i=0
    for pkg in $PACKS; do
        i=$((i + 1))
        if dpkg -s "$pkg" >/dev/null 2>&1; then
            log "[$i/$TOTAL] $pkg da co san"
            INSTALLED=$((INSTALLED + 1))
            continue
        fi
        log "[$i/$TOTAL] Dang cai: $pkg ..."
        if apt-get install -y --no-install-recommends "$pkg" >>"$LOG_FILE" 2>&1; then
            log "      OK: $pkg"
            INSTALLED=$((INSTALLED + 1))
        else
            log "      THAT BAI: $pkg (bo qua, tiep tuc)"
            MISSING=$((MISSING + 1))
        fi
    done
fi

step "Tinh chinh sau cai"
case "$PROFILE" in
    drivers)
        usermod -aG fuse,plugdev,disk user 2>/dev/null || true
        log "Da them user vao nhom fuse/plugdev (dung lai desktop de ap dung)"
        ;;
    dev)
        sudo -u user git config --global init.defaultBranch main 2>/dev/null || true
        sudo -u user git config --global core.editor nano 2>/dev/null || true
        log "Git config mac dinh: init.branch=main, editor=nano"
        ;;
    media)
        update-desktop-database /usr/share/applications 2>/dev/null || true
        log "Cap nhat menu ung dung"
        ;;
esac

step "Don dep apt cache (tiet kiem disk)"
apt-get clean 2>/dev/null || true
rm -rf /var/lib/apt/lists/* 2>/dev/null || true
log "OK"

[ "$ERRORS" -gt 0 ] && finish false || finish true
