FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:1 \
    PORT=8080 \
    RESOLUTION=1600x900 \
    VNC_DEPTH=24 \
    VNC_FPS=120 \
    LANG=C.UTF-8 \
    LANGUAGE=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    MALLOC_ARENA_MAX=2 \
    CODE_SERVER_PORT=8443

RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    dbus-x11 \
    xfwm4 xfce4-panel xfce4-session xfce4-settings xfdesktop4 xfce4-notifyd \
    xfce4-terminal xfce4-screenshooter \
    thunar mousepad xarchiver \
    tigervnc-standalone-server tigervnc-common tigervnc-tools \
    novnc websockify \
    chromium \
    firefox-esr \
    ffmpeg gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav \
    gstreamer1.0-alsa \
    vlc \
    rclone htop onboard xprintidle xdotool \
    gimp \
    libreoffice-writer libreoffice-calc libreoffice-impress \
    arc-theme papirus-icon-theme \
    xfce4-taskmanager \
    tor privoxy proxychains4 \
    pulseaudio \
    wget curl git nano procps ca-certificates \
    sudo zip unzip p7zip-full \
    fonts-dejavu-core fonts-liberation fonts-noto-color-emoji tzdata net-tools iw \
    python3 python3-pip python3-requests python3-psutil python3-aiohttp \
    && pip3 install --no-cache-dir --break-system-packages gdown \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://code-server.dev/install.sh | sh

RUN useradd -m -d /home/user -s /bin/bash user \
    && echo "user ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/user \
    && chmod 0440 /etc/sudoers.d/user

RUN mkdir -p /home/user/{Desktop,Documents,Downloads,.config,.cache,.vnc,.backups,Drive,.local/share/code-server,.wallpapers}

COPY scripts/ /usr/local/bin/
RUN chmod +x /usr/local/bin/*

COPY http-server.py /usr/local/bin/http-server.py
COPY idle-monitor.py /usr/local/bin/idle-monitor.py
COPY resource-watchdog.py /usr/local/bin/resource-watchdog.py
COPY index.html /srv/index.html
COPY wallpaper-gen.py /usr/local/bin/wallpaper-gen.py

COPY start.sh /start.sh
RUN chmod +x /start.sh

COPY supervisord.conf /etc/supervisor/supervisord.conf

EXPOSE 8080

CMD ["/start.sh"]
