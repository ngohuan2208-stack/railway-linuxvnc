FROM debian:bookworm-slim

# ----------------------------------------------------------
# Optional components (build-time).
# Defaults keep the current full feature set (README compatible).
# Slim builds: docker build --build-arg INSTALL_GIMP=0 --build-arg INSTALL_LIBREOFFICE=0 ...
ARG INSTALL_GIMP=1
ARG INSTALL_LIBREOFFICE=1
ARG INSTALL_VLC=1
ARG INSTALL_TOR=1
ARG INSTALL_NODE=1
ARG INSTALL_CODESERVER=1
ARG INSTALL_LXQT=1

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:1 \
    PORT=8080 \
    RESOLUTION=1600x900 \
    VNC_DEPTH=24 \
    VNC_FPS=30 \
    ENABLE_AUDIO=0 \
    LANG=C.UTF-8 \
    LANGUAGE=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    MALLOC_ARENA_MAX=2 \
    CODE_SERVER_PORT=8443 \
    DESKTOP=lxqt \
    IDLE_TIMEOUT=0 \
    BOOT_GRACE_SEC=240 \
    VNC_CONNECT_WINDOW=120 \
    CODE_START_TIMEOUT=30 \
    VNC_PUBLIC=0

# Install core packages in a single layer for better caching
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    dbus dbus-x11 \
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
    rclone htop onboard xprintidle \
    arc-theme papirus-icon-theme \
    xfce4-taskmanager \
    pulseaudio \
    wget curl git nano procps ca-certificates \
    sudo zip unzip p7zip-full \
    fonts-dejavu-core fonts-liberation fonts-noto-color-emoji tzdata net-tools \
    python3 python3-pip python3-psutil python3-aiohttp \
    $( [ "$INSTALL_GIMP" = "1" ] && echo gimp ) \
    $( [ "$INSTALL_LIBREOFFICE" = "1" ] && echo libreoffice-writer libreoffice-calc libreoffice-impress ) \
    $( [ "$INSTALL_VLC" = "1" ] && echo vlc ) \
    $( [ "$INSTALL_TOR" = "1" ] && echo "tor privoxy proxychains4" ) \
    $( [ "$INSTALL_LXQT" = "1" ] && echo "lxqt-core openbox pcmanfm-qt qterminal lxqt-themes qt5ct" ) \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* \
              /usr/share/doc/* /usr/share/man/* /tmp/*

# Build-time smoke test: the image must FAIL TO BUILD (not crash-loop at
# runtime) when the HTTP server's dependencies are missing. This is the
# guard against the "httpserver exits 1 after ~200ms forever" failure mode.
RUN python3 -c "import aiohttp, psutil; print('python deps ok: aiohttp', aiohttp.__version__)"

RUN if [ "$INSTALL_NODE" = "1" ]; then \
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
        && apt-get install -y --no-install-recommends nodejs \
        && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*; \
    fi

RUN if [ "$INSTALL_CODESERVER" = "1" ]; then \
        curl -fsSL https://code-server.dev/install.sh | sh; \
    fi

RUN useradd -m -d /home/user -s /bin/bash user \
    && echo "user ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/user \
    && chmod 0440 /etc/sudoers.d/user

RUN mkdir -p /home/user/{Desktop,Documents,Downloads,Projects,.config,.cache,.vnc,.backups,Drive,.local/share/code-server,.wallpapers}

# Backend scripts + python sources (v2: lazy asyncio.Lock init)
COPY scripts/ /usr/local/bin/
COPY http-server.py idle-monitor.py resource-watchdog.py wallpaper-gen.py \
     /usr/local/bin/
RUN chmod +x /usr/local/bin/* \
    && cp /usr/local/bin/optimize.sh /usr/local/bin/optimize-system \
    && cp /usr/local/bin/os-profile.sh /usr/local/bin/os-profile \
    && cp /usr/local/bin/install-vscode.sh /usr/local/bin/install-vscode \
    && chmod +x /usr/local/bin/optimize-system /usr/local/bin/os-profile \
                 /usr/local/bin/install-vscode

COPY start.sh /start.sh
COPY supervisord.conf /etc/supervisor/supervisord.conf

# Pre-generate default + gradient presets (tiny PNGs) so the wallpaper
# picker works offline and instantly.
RUN chmod +x /start.sh \
    && mkdir -p /opt/wallpapers \
    && python3 /usr/local/bin/wallpaper-gen.py /opt/wallpaper.png 1600 900 \
    && python3 /usr/local/bin/wallpaper-gen.py /opt/wallpapers/midnight.png 1600 900 10 14 23 30 41 59 \
    && python3 /usr/local/bin/wallpaper-gen.py /opt/wallpapers/aurora.png 1600 900 13 115 119 88 28 135 \
    && python3 /usr/local/bin/wallpaper-gen.py /opt/wallpapers/sunset.png 1600 900 194 65 12 190 24 93 \
    && python3 /usr/local/bin/wallpaper-gen.py /opt/wallpapers/ocean.png 1600 900 8 47 73 6 182 212 \
    && python3 /usr/local/bin/wallpaper-gen.py /opt/wallpapers/neon.png 1600 900 76 29 149 236 72 153 \
    && python3 /usr/local/bin/wallpaper-gen.py /opt/wallpapers/forest.png 1600 900 6 58 40 16 185 129

# Most volatile file last: UI edits no longer invalidate any earlier layer.
COPY index.html /srv/index.html

EXPOSE 8080

CMD ["/start.sh"]
