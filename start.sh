#!/bin/bash
# ============================================================
# Railway Linux Desktop - container entrypoint
# Boot flow:
#   env validation -> filesystem init -> dbus -> supervisord
#   -> wait 5901 -> [VNC] Ready -> XFCE ready -> SYSTEM READY
# The HTTP server starts immediately (Railway healthcheck),
# but /health reports honest component states during boot.
# ============================================================
set -e

# ---------------- defaults & validation ----------------
PORT=${PORT:-8080}
RESOLUTION=${RESOLUTION:-1600x900}
VNC_DEPTH=${VNC_DEPTH:-24}
VNC_FPS=${VNC_FPS:-30}
TZ=${TZ:-}
AUTO_BACKUP=${AUTO_BACKUP:-1}
BACKUP_INTERVAL_MIN=${BACKUP_INTERVAL_MIN:-30}
AUTO_BACKUP_ON_EXIT=${AUTO_BACKUP_ON_EXIT:-1}
IDLE_TIMEOUT=${IDLE_TIMEOUT:-0}          # 24/7: suspend disabled by default
IDLE_CHECK=${IDLE_CHECK:-10}
DROP_CACHE=${DROP_CACHE:-1}
ENABLE_PROXY=${ENABLE_PROXY:-0}
ENABLE_AUDIO=${ENABLE_AUDIO:-0}
MEM_LIMIT_MB=${MEM_LIMIT_MB:-1228}
CPU_MAX_PCT=${CPU_MAX_PCT:-85}
DISK_CLEAN_PCT=${DISK_CLEAN_PCT:-80}
WATCHDOG_INTERVAL=${WATCHDOG_INTERVAL:-5}
BOOT_GRACE_SEC=${BOOT_GRACE_SEC:-240}
# Desktop environment: lxqt (default, lighter) | xfce (classic, opt-in)
DESKTOP=${DESKTOP:-lxqt}
case "$DESKTOP" in xfce|lxqt) ;; *) DESKTOP=lxqt ;; esac

# Public VNC (app client qua Railway TCP Proxy): 0 = chi nghe localhost
case "${VNC_PUBLIC:-0}" in 1|true|TRUE|yes) VNC_PUBLIC=1 ;; *) VNC_PUBLIC=0 ;; esac
VNC_TCP_PROXY=${VNC_TCP_PROXY:-}

# Maximum concurrent VNC connections
MAX_VNC_CONNECTIONS=${MAX_VNC_CONNECTIONS:-3}

case "$PORT" in ''|*[!0-9]*) PORT=8080 ;; esac
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then PORT=8080; fi
case "$RESOLUTION" in ''|*[!0-9x]*|*x*x*) RESOLUTION=1600x900 ;; esac
case "$VNC_DEPTH" in 16|24) ;; *) VNC_DEPTH=24 ;; esac
case "$VNC_FPS" in ''|*[!0-9]*) VNC_FPS=30 ;; esac
[ "$VNC_FPS" -lt 1 ] && VNC_FPS=30; [ "$VNC_FPS" -gt 60 ] && VNC_FPS=60
case "$IDLE_TIMEOUT" in ''|*[!0-9]*) IDLE_TIMEOUT=0 ;; esac
case "$MEM_LIMIT_MB" in ''|*[!0-9]*) MEM_LIMIT_MB=1228 ;; esac
# These feed int() parsers in watchdog/backup scripts - garbage here would
# crash-loop them exactly like a broken httpserver.
case "$CPU_MAX_PCT" in ''|*[!0-9]*) CPU_MAX_PCT=85 ;; esac
case "$DISK_CLEAN_PCT" in ''|*[!0-9]*) DISK_CLEAN_PCT=80 ;; esac
case "$WATCHDOG_INTERVAL" in ''|*[!0-9]*) WATCHDOG_INTERVAL=5 ;; esac
case "$BACKUP_INTERVAL_MIN" in ''|*[!0-9]*) BACKUP_INTERVAL_MIN=30 ;; esac
case "$MAX_VNC_CONNECTIONS" in ''|*[!0-9]*) MAX_VNC_CONNECTIONS=3 ;; esac

export PORT RESOLUTION VNC_DEPTH VNC_FPS TZ IDLE_TIMEOUT IDLE_CHECK DROP_CACHE
export AUTO_BACKUP BACKUP_INTERVAL_MIN AUTO_BACKUP_ON_EXIT ENABLE_PROXY ENABLE_AUDIO
export MEM_LIMIT_MB CPU_MAX_PCT DISK_CLEAN_PCT WATCHDOG_INTERVAL BOOT_GRACE_SEC
export DESKTOP
export VNC_PUBLIC="${VNC_PUBLIC:-0}" VNC_TCP_PROXY="${VNC_TCP_PROXY:-}"
export MAX_VNC_CONNECTIONS

mkdir -p /var/log/supervisor /var/log
touch /var/log/boot.log

blog() {
    echo "$@"
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> /var/log/boot.log
}

# ---------------- RESERVED PORT GUARD ----------------
# A PORT that collides with an internal service (Xvnc 5901, code-server
# 8443) makes the HTTP server die with 'address already in use' FOREVER ->
# Railway healthcheck never passes (observed in production: PORT=5901 got
# injected/set, httpserver crash-looped for the whole deploy timeout).
if [ "$PORT" = "5901" ] || [ "$PORT" = "${CODE_SERVER_PORT:-8443}" ]; then
    echo "[WARN] PORT=$PORT trung voi port noi bo (Xvnc/code-server) -> ep ve 8080"
    echo "$(date '+%Y-%m-%d %H:%M:%S') [WARN] PORT=$PORT collided with internal service, forced to 8080" >> /var/log/boot.log
    PORT=8080
fi

# Write default config ONLY if missing -> user customizations (wallpaper,
# panel, themes...) survive container restarts on a persistent volume.
write_once() {
    local f="$1"
    if [ -f "$f" ]; then return 0; fi
    mkdir -p "$(dirname "$f")"
    cat > "$f"
}

blog "[BOOT] Railway Linux Desktop starting"

# ---------------- TIMEZONE ----------------
if [ -n "$TZ" ] && [ -f "/usr/share/zoneinfo/$TZ" ]; then
    ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime
    echo "$TZ" > /etc/timezone
fi

# ---------------- USER SETUP ----------------
if ! id user >/dev/null 2>&1; then
    useradd -m -d /home/user -s /bin/bash user
    echo "user ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/user
    chmod 0440 /etc/sudoers.d/user
fi
# Volume-mounted /home may hide the image home dir - recreate skeleton.
if [ ! -d /home/user ]; then
    mkdir -p /home/user
    cp -a /etc/skel/. /home/user/ 2>/dev/null || true
fi

mkdir -p /home/user/{Desktop,Documents,Downloads,Projects,.config,.cache,.vnc,.backups,Drive,.local/share/code-server,.wallpapers,.ssh}
chmod 700 /home/user/.ssh 2>/dev/null || true

blog "[BOOT] Environment OK (DESKTOP=$DESKTOP)"
blog "[BOOT] Storage OK (/home/user initialized)"

# ---------------- VNC AUTH ----------------
# Default password: railwaylinux (change via VNC_PASSWORD env).
# Set VNC_PASSWORD=none|0|off to disable auth entirely (localhost-only).
VNC_PASSWORD=${VNC_PASSWORD:-railwaylinux}
case "$(echo "$VNC_PASSWORD" | tr '[:upper:]' '[:lower:]')" in
    none|0|off) VNC_PASSWORD="" ;;
esac
rm -f /home/user/.vnc/passwd
if [ -n "$VNC_PASSWORD" ]; then
    printf '%s' "$VNC_PASSWORD" | vncpasswd -f > /home/user/.vnc/passwd
    chmod 600 /home/user/.vnc/passwd
    blog "[VNC] auth = VncAuth (default railwaylinux, override via VNC_PASSWORD)"
else
    blog "[VNC] auth = None (disabled via VNC_PASSWORD, localhost-only bridge)"
fi
# Marker for http-server: expose the password to noVNC ONLY when it is the
# public default (admin has not customized VNC_PASSWORD).
if [ "$VNC_PASSWORD" = "railwaylinux" ]; then
    VNC_PASSWORD_DEFAULTED=1
fi
export VNC_PASSWORD VNC_PASSWORD_DEFAULTED
if [ "$VNC_PUBLIC" = "1" ]; then
    blog "[VNC] public bind 0.0.0.0:5901 (TCP proxy: ${VNC_TCP_PROXY:-chua cau hinh})"
fi

write_once /home/user/.vnc/xstartup << 'XSTARTUP'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
export XDG_SESSION_DESKTOP=XFCE
exec dbus-launch --exit-with-session startxfce4
XSTARTUP
chmod +x /home/user/.vnc/xstartup

# ---------------- XVNC RUNNER ----------------
# Generated at boot so security flags depend on VNC_PASSWORD presence.
# VNC_PUBLIC=1 -> Xvnc listen 0.0.0.0 (dung voi Railway TCP Proxy de ket
# noi bang app VNC that: RealVNC / TigerVNC / RVNC viewer...).
mkdir -p /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1   # stale locks from previous run
if [ "$VNC_PUBLIC" = "1" ]; then
    if [ -z "$VNC_PASSWORD" ]; then
        blog "[WARN] VNC_PUBLIC=1 ma khong co mat khau - AI NGUOI LA CUNG DIEU KHIEN DUOC DESKTOP!"
    fi
    XNC_BIND="-localhost no"
else
    XNC_BIND="-localhost yes"
fi
cat > /usr/local/bin/run-xvnc.sh << RUNXVNC
#!/bin/sh
SECARGS="-SecurityTypes None"
if [ -s /home/user/.vnc/passwd ]; then
    SECARGS="-SecurityTypes VncAuth -PasswordFile /home/user/.vnc/passwd"
fi
# NOTE: only TigerVNC-supported options here. Debian bookworm Xvnc has NO
# -QualityLevel/-CompressionLevel/-MaxCutPending (they crash startup).
# Optimized for multi-user support with ${MAX_VNC_CONNECTIONS} concurrent connections
exec Xvnc :1 \\
    -geometry ${RESOLUTION} -depth ${VNC_DEPTH} \\
    -rfbport 5901 ${XNC_BIND} \\
    \$SECARGS \\
    -AlwaysShared \\
    -FrameRate ${VNC_FPS} -CompareFB 2 -ZlibLevel 6 \\
    -BlacklistThreshold=0 -UseBlacklist=0 \\
    -Log "*:stderr:30"
RUNXVNC
chmod +x /usr/local/bin/run-xvnc.sh
chown -R user:user /home/user/.vnc

# ---------------- DESKTOP SESSION LAUNCHER ----------------
cat > /usr/local/bin/run-desktop.sh << RUNDESKTOP
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
export XDG_SESSION_DESKTOP=${DESKTOP}
export DISPLAY=:1
# keep the screen always on (24/7 visibility)
xset s off -dpms 2>/dev/null || true
if [ "${DESKTOP}" = "xfce" ]; then
    exec dbus-launch --exit-with-session startxfce4
else
    exec dbus-launch --exit-with-session startlxqt
fi
RUNDESKTOP
chmod +x /usr/local/bin/run-desktop.sh

# ---------------- WALLPAPER PRESETS (sinh dong, pre-built in image) --------
if [ -d /opt/wallpapers ]; then
    mkdir -p /home/user/.wallpapers/presets
    cp -n /opt/wallpapers/*.png /home/user/.wallpapers/presets/ 2>/dev/null || true
fi

# ---------------- XFCE PERFORMANCE (only for DESKTOP=xfce) ----------------
mkdir -p /home/user/.config/xfce4/xfconf/xfce-perchannel-xml
write_once /home/user/.config/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml << 'XFWM4'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfwm4" version="1.0">
  <property name="general" type="empty">
    <property name="use_compositing" type="bool" value="false"/>
    <property name="show_frame_shadow" type="bool" value="false"/>
    <property name="do_edge_swap" type="bool" value="false"/>
    <property name="placement_ratio" type="int" value="50"/>
    <property name="snap_to_border" type="bool" value="true"/>
    <property name="snap_to_windows" type="bool" value="true"/>
    <property name="tile_only_maximized" type="bool" value="true"/>
  </property>
</channel>
XFWM4

# ---------------- LXQT CONFIG (only for DESKTOP=lxqt) ----------------
if [ "$DESKTOP" = "lxqt" ]; then
    mkdir -p /home/user/.config/lxqt /home/user/.config/openbox
    write_once /home/user/.config/lxqt/lxqt.conf << 'LXQT'
[General]
theme=dark
icon_theme=Papirus-Dark
style=fusion
single_click_activate=false
LXQT

    write_once /home/user/.config/lxqt/session.conf << 'LXSESS'
[General]
__userfile__=true
window_manager=openbox

[Environment]
GTK_CSD=0
GTK_OVERLAY_SCROLLING=0
LXSESS

    # no screensaver / screen locking - desktop stays visible 24/7
    mkdir -p /home/user/.config/autostart
    for a in xscreensaver lxqt-xscreensaver-autostart; do
        printf '[Desktop Entry]\nType=Application\nHidden=true\n' \
            > "/home/user/.config/autostart/${a}.desktop"
    done

    # Arc-Dark window decorations, no compositor, no shadows
    write_once /home/user/.config/openbox/lxqt-rc.xml << 'OBRC'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <theme>
    <name>Arc-Dark</name>
    <titleLayout>NLMIC</titleLayout>
  </theme>
  <placement>
    <policy>Smart</policy>
  </placement>
</openbox_config>
OBRC

    # pcmanfm-qt desktop wallpaper default (user changes preserved)
    write_once /home/user/.config/pcmanfm-qt/lxqt/settings.conf << 'PCMANFM'
[General]
Wallpaper=/home/user/.wallpapers/default.png
WallpaperMode=stretch
PCMANFM
fi

write_once /home/user/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-power-manager.xml << 'XFPM'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-power-manager" version="1.0">
  <property name="xfce4-power-manager" type="empty">
    <property name="show-tray-icon" type="bool" value="false"/>
    <property name="presentation-mode" type="bool" value="true"/>
    <property name="inactivity-on-ac" type="uint" value="0"/>
    <property name="dpms-enabled" type="bool" value="false"/>
    <property name="lock-screen-suspend-hibernate" type="bool" value="false"/>
  </property>
</channel>
XFPM

# Disable screen blanking inside the X session (24/7 visibility)
write_once /home/user/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-screensaver.xml << 'XSS'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-screensaver" version="1.0">
  <property name="saver" type="empty">
    <property name="enabled" type="bool" value="false"/>
  </property>
  <property name="lock" type="empty">
    <property name="enabled" type="bool" value="false"/>
  </property>
</channel>
XSS

# ---------------- DOCK PANEL ----------------
mkdir -p /home/user/.config/xfce4/panel
write_once /home/user/.config/xfce4/panel/whiskermenu-1.rc << 'WHISKER'
[button]
style=3
custom-name=Applications
WHISKER

write_once /home/user/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml << 'PANEL'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-panel" version="1.0">
  <property name="configver" type="int" value="2"/>
  <property name="panels" type="array">
    <value type="int" value="1"/>
    <property name="panel-1" type="empty">
      <property name="position" type="string" value="p=10;x=0;y=0"/>
      <property name="length" type="uint" value="40"/>
      <property name="position-locked" type="bool" value="true"/>
      <property name="background-style" type="uint" value="1"/>
      <property name="background-rgba" type="array">
        <value type="double" value="0.05"/>
        <value type="double" value="0.05"/>
        <value type="double" value="0.08"/>
        <value type="double" value="0.75"/>
      </property>
      <property name="icon-size" type="uint" value="36"/>
      <property name="mode" type="int" value="1"/>
    </property>
  </property>
  <property name="plugins" type="array">
    <value type="string" value="plugin-1"/>
    <value type="string" value="plugin-2"/>
    <value type="string" value="plugin-3"/>
    <value type="string" value="plugin-4"/>
    <value type="string" value="plugin-5"/>
    <value type="string" value="plugin-6"/>
    <value type="string" value="plugin-7"/>
  </property>
  <property name="plugin-1" type="string" value="whiskermenu"/>
  <property name="plugin-2" type="string" value="separator">
    <property name="expand" type="bool" value="false"/>
    <property name="style" type="uint" value="0"/>
  </property>
  <property name="plugin-3" type="string" value="launcher">
    <property name="items" type="array">
      <value type="string" value="firefox-esr.desktop"/>
    </property>
  </property>
  <property name="plugin-4" type="string" value="launcher">
    <property name="items" type="array">
      <value type="string" value="chromium.desktop"/>
    </property>
  </property>
  <property name="plugin-5" type="string" value="launcher">
    <property name="items" type="array">
      <value type="string" value="org.xfce.terminal.desktop"/>
    </property>
  </property>
  <property name="plugin-6" type="string" value="launcher">
    <property name="items" type="array">
      <value type="string" value="thunar.desktop"/>
    </property>
  </property>
  <property name="plugin-7" type="string" value="tasklist">
    <property name="flat-buttons" type="bool" value="true"/>
  </property>
</channel>
PANEL

# ---------------- GTK THEME (dark) ----------------
mkdir -p /home/user/.config/gtk-3.0
write_once /home/user/.config/gtk-3.0/settings.ini << 'GTK3'
[Settings]
gtk-theme-name=Arc-Dark
gtk-icon-theme-name=Papirus-Dark
gtk-font-name=DejaVu Sans 10
gtk-cursor-theme-name=Adwaita
gtk-toolbar-style=GTK_TOOLBAR_ICONS
gtk-toolbar-icon-size=GTK_ICON_SIZE_LARGE_TOOLBAR
gtk-button-images=0
gtk-menu-images=0
GTK3

write_once /home/user/.gtkrc-2.0 << 'GTK2'
gtk-theme-name="Arc-Dark"
gtk-icon-theme-name="Papirus-Dark"
gtk-font-name="DejaVu Sans 10"
GTK2

# ---------------- WALLPAPER ----------------
mkdir -p /home/user/.wallpapers/presets
if [ ! -f /home/user/.wallpapers/default.png ]; then
    if [ -f /opt/wallpaper.png ]; then
        cp -f /opt/wallpaper.png /home/user/.wallpapers/default.png 2>/dev/null || true
    else
        python3 /usr/local/bin/wallpaper-gen.py /home/user/.wallpapers/default.png 1600 900 2>/dev/null || true
    fi
fi

write_once /home/user/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml << 'WALLPAPER'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-desktop" version="1.0">
  <property name="backdrop" type="empty">
    <property name="screen0" type="empty">
      <property name="monitor0" type="empty">
        <property name="workspace0" type="empty">
          <property name="last-image" type="string" value="/home/user/.wallpapers/default.png"/>
          <property name="image-style" type="int" value="5"/>
          <property name="color1" type="string" value="#0a0e17"/>
          <property name="color2" type="string" value="#111827"/>
          <property name="show-image" type="bool" value="true"/>
        </property>
      </property>
    </property>
  </property>
</channel>
WALLPAPER

# ---------------- ONBOARD ----------------
mkdir -p /home/user/.config/onboard
write_once /home/user/.config/onboard/onboard.conf << 'ONBOARD'
[com Canonical Onboard]
theme = 'Dark'
gtk theme = 'Dark'
orientation = 'bottom'
width = 800
height = 220
enable-repositioning = true
show-on-force-touchscreen = false
ONBOARD

# ---------------- PULSEAUDIO (only when ENABLE_AUDIO=1) ----------------
mkdir -p /home/user/.config/pulse
write_once /home/user/.config/pulse/default.pa << 'PULSE'
.include /etc/pulse/default.pa
PULSE

# ---------------- CODE-SERVER (lazy started via UI) ----------------
mkdir -p /home/user/.config/code-server
write_once /home/user/.config/code-server/config.yaml << 'CODESERVER'
bind-addr: 127.0.0.1:8443
auth: none
cert: false
CODESERVER

# ---------------- CHROMIUM ----------------
mkdir -p /home/user/.config/chromium/Default
if [ ! -f /home/user/.config/chromium/Default/Preferences ]; then
write_once /home/user/.config/chromium/Default/Preferences << 'CHROMIUM'
{
  "hardware_acceleration_mode": {"enabled": false},
  "browser": {"check_default_browser": false},
  "profile": {"default_content_setting_values": {"notifications": 2}}
}
CHROMIUM
fi

# ---------------- AI CLI ----------------
# Config is REWRITTEN each boot from Railway env (AI_API_LINK/AI_API_KEY/
# AI_MODEL/...) so changing a variable on Railway updates the OS config.
# The `ai` CLI + safety filter live in /usr/local/bin (baked in image).
export AI_API_LINK="${AI_API_LINK:-${AI_API_URL:-}}" AI_API_KEY="${AI_API_KEY:-}"
export AI_MODEL="${AI_MODEL:-}" AI_NAME="${AI_NAME:-AI Assistant}"
export AI_PROVIDER="${AI_PROVIDER:-openai}" AI_EXEC_TIMEOUT="${AI_EXEC_TIMEOUT:-240}"
mkdir -p /home/user/.ai-cli /home/user/.config/os-profiles
# Ghi qua python3 de JSON luon hop le (key co the chua ky tu dac biet)
python3 - << 'PYAI'
import json, os
cfg = {
    "provider": os.environ.get("AI_PROVIDER", "openai"),
    "api_link": os.environ.get("AI_API_LINK", ""),
    "api_key": os.environ.get("AI_API_KEY", ""),
    "model": os.environ.get("AI_MODEL", ""),
    "name": os.environ.get("AI_NAME", "AI Assistant"),
}
with open("/home/user/.ai-cli/config.json", "w") as f:
    json.dump(cfg, f, indent=2)
PYAI
chmod 600 /home/user/.ai-cli/config.json 2>/dev/null || true
chown -R user:user /home/user/.ai-cli 2>/dev/null || true
if [ -n "$AI_API_LINK" ] && [ -n "$AI_API_KEY" ] && [ -n "$AI_MODEL" ]; then
    blog "[BOOT] AI CLI ready ($AI_NAME / $AI_MODEL)"
else
    blog "[BOOT] AI CLI disabled (set AI_API_LINK, AI_API_KEY, AI_MODEL to enable)"
fi

# ---------------- FIREFOX ----------------
mkdir -p /home/user/.mozilla/firefox/default-release
if [ ! -f /home/user/.mozilla/firefox/default-release/user.js ]; then
write_once /home/user/.mozilla/firefox/default-release/user.js << 'FIREFOX'
user_pref("media.hardware-video-decoding.force-enabled", false);
user_pref("gfx.webrender.all", true);
user_pref("media.ffmpeg.vaapi.enabled", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
FIREFOX
fi

# ---------------- TOR PROXY (optional) ----------------
if [ "$ENABLE_PROXY" = "1" ]; then
    mkdir -p /home/user/.config/tor
    cat > /home/user/.config/tor/torrc << 'TOR'
SocksPort 9050
DataDirectory /home/user/.config/tor/data
Log notice stdout
TOR

    cat > /etc/privoxy/config << 'PRIVOXY'
listen-address 127.0.0.1:8118
forward-socks5 / 127.0.0.1:9050 .
PRIVOXY

    cat > /etc/proxychains4.conf << 'PROXYCHAINS'
strict_chain
proxy_dns
[ProxyList]
socks5 127.0.0.1 9050
PROXYCHAINS
    blog "[BOOT] Tor proxy enabled"
fi

# ---------------- PERMISSIONS ----------------
# Top-level + small dirs only; a recursive chown over a big Railway volume
# would slow every boot and touch user data timestamps.
chown user:user /home/user
for d in Desktop Documents Downloads Projects Drive .backups .wallpapers .cache .local .ssh; do
    chown -R user:user "/home/user/$d" 2>/dev/null || true
done
chown -R user:user /home/user/.config 2>/dev/null || true

# ---------------- DBUS ----------------
mkdir -p /run/dbus
rm -f /run/dbus/pid
dbus-uuidgen --ensure 2>/dev/null || true
blog "[BOOT] D-Bus OK"

# ---------------- SHUTDOWN HANDLER ----------------
_term_handler() {
    echo "SIGTERM: saving data..."
    if [ "$AUTO_BACKUP_ON_EXIT" = "1" ]; then
        /usr/local/bin/backup-data 2>/dev/null || true
    fi
    echo "Stopping services..."
    kill "$SUP_PID" 2>/dev/null
    wait "$SUP_PID" 2>/dev/null
    echo "Shutdown complete."
    exit 0
}
trap _term_handler SIGTERM SIGINT

# ---------------- PREFLIGHT: python deps of the HTTP server ----------------
# httpserver needs aiohttp+psutil. If they are missing it would crash-loop
# forever (exit 1 ~200ms after spawn) and /health would never answer ->
# Railway deploy FAILED with no obvious cause. Fail FAST and LOUD instead.
if ! python3 -c 'import aiohttp, psutil' >/dev/null 2>&1; then
    blog "[ERROR] python3 dependencies missing (aiohttp/psutil) - HTTP server cannot start."
    blog "[ERROR] Fix: redeploy WITHOUT build cache (docker build --no-cache / Railway redeploy)."
    blog "[ERROR] Aborting boot so the root cause stays visible in deploy logs."
    exit 1
fi
blog "[BOOT] Python deps OK (aiohttp + psutil)"

# ---------------- START SUPERVISORD ----------------
/usr/bin/supervisord -c /etc/supervisor/supervisord.conf &
SUP_PID=$!
blog "[HTTP] Starting server (port $PORT)"
blog "[WS] WebSocket bridge pending"

# ---------------- READINESS GATE (background reporter) ----------------
port_open() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

(
    # [VNC] wait for port 5901
    VNC_DEADLINE=$(( $(date +%s) + BOOT_GRACE_SEC ))
    VNC_UP=0
    while [ "$(date +%s)" -lt "$VNC_DEADLINE" ]; do
        if port_open 5901; then VNC_UP=1; break; fi
        sleep 1
    done
    if [ "$VNC_UP" != "1" ]; then
        blog "[ERROR] VNC failed to open 5901 within ${BOOT_GRACE_SEC}s"
        exit 0
    fi
    blog "[VNC] Waiting for 5901... done"
    blog "[VNC] Ready"

    # [DE] wait for session process
    SESSION_PROC=xfce4-session
    [ "$DESKTOP" = "lxqt" ] && SESSION_PROC=lxqt-session
    XF_DEADLINE=$(( $(date +%s) + BOOT_GRACE_SEC ))
    while [ "$(date +%s)" -lt "$XF_DEADLINE" ]; do
        if pgrep -x "$SESSION_PROC" >/dev/null 2>&1; then
            blog "[${DESKTOP^^}] Starting desktop... done"
            blog "[${DESKTOP^^}] Ready"
            blog "[WS] WebSocket bridge ready"
            blog "[SYSTEM] Desktop READY"
            exit 0
        fi
        sleep 1
    done
    blog "[ERROR] Desktop ($SESSION_PROC) did not start within ${BOOT_GRACE_SEC}s (watchdog will retry)"
) &

wait "$SUP_PID"
