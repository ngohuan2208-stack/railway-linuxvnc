#!/bin/bash

set -e

PORT=${PORT:-8080}
VNC_PASSWORD=${VNC_PASSWORD:-linuxdesktop}

echo "=== Linux Desktop Startup ==="
echo "PORT: $PORT"

mkdir -p /home/user/.vnc
echo "$VNC_PASSWORD" | vncpasswd -f > /home/user/.vnc/passwd
chmod 600 /home/user/.vnc/passwd

cat > /home/user/.vnc/xstartup << 'XSTARTUP'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
export XDG_SESSION_DESKTOP=XFCE
exec startxfce4
XSTARTUP
chmod +x /home/user/.vnc/xstartup
chown -R user:user /home/user/.vnc

chown -R user:user /home/user

mkdir -p /run/dbus
rm -f /run/dbus/pid
dbus-uuidgen --ensure

mkdir -p /var/log/supervisor

exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
