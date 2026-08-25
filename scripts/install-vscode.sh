#!/bin/bash
# ============================================================
# install-vscode: cai Visual Studio Code ban PC (native .deb)
# Chay boi /api/tasks/run/vscode - output stream ra web terminal.
# Exit: 0 = OK, 1 = loi
# ============================================================
set -u

LOG_FILE="/var/log/install-vscode.log"
STEP=0
START_TS=$(date +%s)

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

touch "$LOG_FILE" 2>/dev/null || LOG_FILE=/tmp/install-vscode.log

log "=== Cai Visual Studio Code (PC) ==="

ARCH="$(dpkg --print-architecture 2>/dev/null || echo unknown)"
step "Kiem tra kien truc (${ARCH})"
if [ "$ARCH" != "amd64" ]; then
    log "FAIL: VS Code chi phat hanh .deb cho amd64 (container la ${ARCH})."
    log "Hay dung VS Code web: nut VS Code o sidebar (code-server)."
    echo "TASK_RESULT_JSON:{\"ok\":false,\"reason\":\"arch=${ARCH}\",\"duration_s\":$(($(date +%s) - START_TS))}"
    exit 1
fi
log "OK: amd64"

DEB="/tmp/vscode.deb"
URL="https://code.visualstudio.com/sha/download?build=stable&os=linux-deb-x64"
rm -f "$DEB"
step "Tai go .deb tu microsoft.com (~100MB)"
log "Dang tai: $URL"
wget -q -O "$DEB" "$URL" &
WPID=$!
DL_FAIL=0
while kill -0 "$WPID" 2>/dev/null; do
    sleep 5
    CUR_MB=$(du -m "$DEB" 2>/dev/null | cut -f1)
    log "  ...da tai ${CUR_MB:-0}MB"
done
wait "$WPID" || DL_FAIL=1
if [ "$DL_FAIL" = "1" ] || [ ! -s "$DEB" ]; then
    log "FAIL: khong tai duoc go .deb (kiem tra mang)."
    echo "TASK_RESULT_JSON:{\"ok\":false,\"reason\":\"download failed\",\"duration_s\":$(($(date +%s) - START_TS))}"
    exit 1
fi
SIZE_MB=$(( $(stat -c%s "$DEB" 2>/dev/null || echo 0) / 1048576 ))
log "OK: da tai ${SIZE_MB}MB"

step "Cai dat (apt)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq 2>>"$LOG_FILE" || true
if apt-get install -y "$DEB" >>"$LOG_FILE" 2>&1; then
    log "OK: apt install thanh cong"
else
    log "apt that bai, thu dpkg + fix dependency..."
    if dpkg -i "$DEB" >>"$LOG_FILE" 2>&1 && apt-get install -f -y >>"$LOG_FILE" 2>&1; then
        log "OK: dpkg + apt-get -f thanh cong"
    else
        log "FAIL: cai dat that bai. Xem log: $LOG_FILE"
        rm -f "$DEB"
        echo "TASK_RESULT_JSON:{\"ok\":false,\"reason\":\"install failed\",\"duration_s\":$(($(date +%s) - START_TS))}"
        exit 1
    fi
fi
rm -f "$DEB"

step "Kiem tra + tao icon Desktop"
BIN="$(command -v code || true)"
if [ -z "$BIN" ]; then
    log "FAIL: khong tim thay lenh 'code' sau khi cai."
    echo "TASK_RESULT_JSON:{\"ok\":false,\"reason\":\"binary missing\",\"duration_s\":$(($(date +%s) - START_TS))}"
    exit 1
fi
VERSION="$("$BIN" --version 2>/dev/null | head -n1 || echo '?')"
if [ -f /usr/share/applications/code.desktop ]; then
    cp -f /usr/share/applications/code.desktop /home/user/Desktop/ 2>/dev/null || true
    chmod +x /home/user/Desktop/code.desktop 2>/dev/null || true
fi
chown user:user /home/user/Desktop/code.desktop 2>/dev/null || true
update-desktop-database /usr/share/applications 2>/dev/null || true
log "OK: code ${VERSION%% *} -> $BIN (icon tren Desktop)"

DUR=$(($(date +%s) - START_TS))
log ""
log "Hoan thanh trong ${DUR}s. Mo VS Code tu menu Applications hoac chay: code"
echo "TASK_RESULT_JSON:{\"ok\":true,\"version\":\"${VERSION%% *}\",\"path\":\"$BIN\",\"errors\":0,\"duration_s\":${DUR}}"
exit 0
