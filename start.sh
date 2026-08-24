#!/bin/bash
set -e

PORT=${PORT:-8080}
VNC_PASSWORD=${VNC_PASSWORD:-linuxdesktop}
RESOLUTION=${RESOLUTION:-1600x900}
VNC_DEPTH=${VNC_DEPTH:-24}
TZ=${TZ:-}
AUTO_BACKUP=${AUTO_BACKUP:-1}
BACKUP_INTERVAL_MIN=${BACKUP_INTERVAL_MIN:-30}
AUTO_BACKUP_ON_EXIT=${AUTO_BACKUP_ON_EXIT:-1}
IDLE_TIMEOUT=${IDLE_TIMEOUT:-300}
IDLE_CHECK=${IDLE_CHECK:-10}
DROP_CACHE=${DROP_CACHE:-1}
ENABLE_PROXY=${ENABLE_PROXY:-0}
VNC_FPS=${VNC_FPS:-120}
MEM_LIMIT_MB=${MEM_LIMIT_MB:-1228}
CPU_MAX_PCT=${CPU_MAX_PCT:-85}
DISK_CLEAN_PCT=${DISK_CLEAN_PCT:-80}
WATCHDOG_INTERVAL=${WATCHDOG_INTERVAL:-5}

export PORT RESOLUTION VNC_DEPTH VNC_FPS TZ
export IDLE_TIMEOUT IDLE_CHECK DROP_CACHE
export AUTO_BACKUP BACKUP_INTERVAL_MIN AUTO_BACKUP_ON_EXIT ENABLE_PROXY
export MEM_LIMIT_MB CPU_MAX_PCT DISK_CLEAN_PCT WATCHDOG_INTERVAL

echo "=== Linux Desktop (XFCE + noVNC + VS Code) ==="
echo "PORT=$PORT RES=$RESOLUTION DEPTH=$VNC_DEPTH"

# --- TIMEZONE ---
if [ -n "$TZ" ] && [ -f "/usr/share/zoneinfo/$TZ" ]; then
    ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime
    echo "$TZ" > /etc/timezone
fi

# --- USER SETUP ---
if ! id user >/dev/null 2>&1; then
    useradd -m -d /home/user -s /bin/bash user
    echo "user ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/user
    chmod 0440 /etc/sudoers.d/user
fi

mkdir -p /home/user/{Desktop,Documents,Downloads,.config,.cache,.vnc,.backups,Drive,.local/share/code-server,.wallpapers}

# --- VNC ---
echo "$VNC_PASSWORD" | vncpasswd -f > /home/user/.vnc/passwd
chmod 600 /home/user/.vnc/passwd

cat > /home/user/.vnc/xstartup << 'XSTARTUP'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
export XDG_SESSION_DESKTOP=XFCE
exec dbus-launch --exit-with-session startxfce4
XSTARTUP
chmod +x /home/user/.vnc/xstartup

# --- XFCE PERFORMANCE ---
mkdir -p /home/user/.config/xfce4/xfconf/xfce-perchannel-xml
cat > /home/user/.config/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml << 'XFWM4'
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

# --- POWER MANAGER ---
cat > /home/user/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-power-manager.xml << 'XFPM'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-power-manager" version="1.0">
  <property name="xfce4-power-manager" type="empty">
    <property name="show-tray-icon" type="bool" value="false"/>
    <property name="presentation-mode" type="bool" value="true"/>
  </property>
</channel>
XFPM

# --- DOCK PANEL (transparent, bottom) ---
mkdir -p /home/user/.config/xfce4/panel
cat > /home/user/.config/xfce4/panel/whiskermenu-1.rc << 'WHISKER'
[button]
style=3
custom-name=Applications
WHISKER

# Dock panel config
mkdir -p /home/user/.config/xfce4/panel
cat > /home/user/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml << 'PANEL'
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

# --- GTK THEME (dark) ---
mkdir -p /home/user/.config/gtk-3.0
cat > /home/user/.config/gtk-3.0/settings.ini << 'GTK3'
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

cat > /home/user/.gtkrc-2.0 << 'GTK2'
gtk-theme-name="Arc-Dark"
gtk-icon-theme-name="Papirus-Dark"
gtk-font-name="DejaVu Sans 10"
GTK2

# --- WALLPAPER (pre-built in image, instant boot) ---
mkdir -p /home/user/.wallpapers
if [ -f /opt/wallpaper.png ]; then
    cp -f /opt/wallpaper.png /home/user/.wallpapers/default.png 2>/dev/null || true
else
    python3 /usr/local/bin/wallpaper-gen.py /home/user/.wallpapers/default.png 1600 900 2>/dev/null || true
fi

mkdir -p /home/user/.config/xfce4/xfconf/xfce-perchannel-xml
cat > /home/user/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml << 'WALLPAPER'
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

# --- ONBOARD ---
mkdir -p /home/user/.config/onboard
cat > /home/user/.config/onboard/onboard.conf << 'ONBOARD'
[com Canonical Onboard]
theme = 'Dark'
gtk theme = 'Dark'
orientation = 'bottom'
width = 800
height = 220
enable-repositioning = true
show-on-force-touchscreen = false
ONBOARD

# --- PULSEAUDIO (loa: null sink, app không crash khi phát âm thanh) ---
mkdir -p /home/user/.config/pulse
cat > /home/user/.config/pulse/default.pa << 'PULSE'
.include /etc/pulse/default.pa
PULSE

# --- CODE-SERVER ---
mkdir -p /home/user/.config/code-server
cat > /home/user/.config/code-server/config.yaml << 'CODESERVER'
bind-addr: 0.0.0.0:8443
auth: none
cert: false
CODESERVER

# --- CHROMIUM (YouTube fix) ---
mkdir -p /home/user/.config/chromium/Default
cat > /home/user/.config/chromium/Default/Preferences << 'CHROMIUM'
{
  "hardware_acceleration_mode": {"enabled": false},
  "browser": {"check_default_browser": false},
  "profile": {"default_content_setting_values": {"notifications": 2}}
}
CHROMIUM

# --- FIREFOX (YouTube fix) ---
mkdir -p /home/user/.mozilla/firefox/default-release
cat > /home/user/.mozilla/firefox/default-release/user.js << 'FIREFOX'
user_pref("media.hardware-video-decoding.force-enabled", false);
user_pref("gfx.webrender.all", true);
user_pref("media.ffmpeg.vaapi.enabled", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
FIREFOX

# --- TOR PROXY ---
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
fi

# --- PERMISSIONS ---
chown -R user:user /home/user/.vnc
chown -R user:user /home/user/.config
chown user:user /home/user/Desktop
chown user:user /home/user/Documents
chown user:user /home/user/Downloads
chown user:user /home/user/.backups
chown user:user /home/user/Drive
chown -R user:user /home/user 2>/dev/null || true

# --- DBUS ---
mkdir -p /run/dbus
rm -f /run/dbus/pid
dbus-uuidgen --ensure

mkdir -p /var/log/supervisor

# --- SHUTDOWN HANDLER ---
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

/usr/bin/supervisord -c /etc/supervisor/supervisord.conf &
SUP_PID=$!
wait "$SUP_PID"
