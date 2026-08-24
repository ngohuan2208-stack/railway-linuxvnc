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

echo "=== Linux Desktop (XFCE + noVNC + VS Code) ==="
echo "PORT=$PORT RES=$RESOLUTION DEPTH=$VNC_DEPTH"

if [ -n "$TZ" ] && [ -f "/usr/share/zoneinfo/$TZ" ]; then
    ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime
    echo "$TZ" > /etc/timezone
fi

if ! id user >/dev/null 2>&1; then
    useradd -m -d /home/user -s /bin/bash user
    echo "user ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/user
    chmod 0440 /etc/sudoers.d/user
fi

mkdir -p /home/user/{Desktop,Documents,Downloads,.config,.cache,.vnc,.backups,Drive,.local/share/code-server}
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

mkdir -p /home/user/.config/xfce4/xfconf/xfce-perchannel-xml
cat > /home/user/.config/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml << 'XFWM4'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfwm4" version="1.0">
  <property name="general" type="empty">
    <property name="use_compositing" type="bool" value="false"/>
    <property name="show_frame_shadow" type="bool" value="false"/>
    <property name="do_edge_swap" type="bool" value="false"/>
  </property>
</channel>
XFWM4

cat > /home/user/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-power-manager.xml << 'XFPM'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-power-manager" version="1.0">
  <property name="xfce4-power-manager" type="empty">
    <property name="show-tray-icon" type="bool" value="false"/>
  </property>
</channel>
XFPM

mkdir -p /home/user/.config/florence
cat > /home/user/.config/florence/florence.conf << 'FLORENCE'
[keyboard]
width=800
height=220
opacity=0.9
theme=default
[FLORENCE]
startHidden=true
FLORENCE

mkdir -p /home/user/.config/code-server
cat > /home/user/.config/code-server/config.yaml << 'CODESERVER'
bind-addr: 0.0.0.0:8443
auth: none
cert: false
CODESERVER

chown -R user:user /home/user/.vnc
chown -R user:user /home/user/.config
chown user:user /home/user/Desktop
chown user:user /home/user/Documents
chown user:user /home/user/Downloads
chown user:user /home/user/.backups
chown user:user /home/user/Drive
chown -R user:user /home/user 2>/dev/null || true

mkdir -p /run/dbus
rm -f /run/dbus/pid
dbus-uuidgen --ensure

mkdir -p /var/log/supervisor

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
