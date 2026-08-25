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
    IDLE_TIMEOUT=0 \
    BOOT_GRACE_SEC=240 \
    VNC_CONNECT_WINDOW=120 \
    CODE_START_TIMEOUT=30

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
    rclone htop onboard xprintidle xdotool \
    arc-theme papirus-icon-theme \
    xfce4-taskmanager \
    pulseaudio \
    wget curl git nano procps ca-certificates \
    sudo zip unzip p7zip-full \
    fonts-dejavu-core fonts-liberation fonts-noto-color-emoji tzdata net-tools \
    python3 python3-pip python3-requests python3-psutil python3-aiohttp \
    $( [ "$INSTALL_GIMP" = "1" ] && echo gimp ) \
    $( [ "$INSTALL_LIBREOFFICE" = "1" ] && echo libreoffice-writer libreoffice-calc libreoffice-impress ) \
    $( [ "$INSTALL_VLC" = "1" ] && echo vlc ) \
    $( [ "$INSTALL_TOR" = "1" ] && echo "tor privoxy proxychains4" ) \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* \
              /usr/share/doc/* /usr/share/man/* /tmp/*

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

COPY scripts/ /usr/local/bin/
RUN chmod +x /usr/local/bin/* \
    && cp /usr/local/bin/optimize.sh /usr/local/bin/optimize-system \
    && chmod +x /usr/local/bin/optimize-system

COPY http-server.py /usr/local/bin/http-server.py
COPY idle-monitor.py /usr/local/bin/idle-monitor.py
COPY resource-watchdog.py /usr/local/bin/resource-watchdog.py
COPY index.html /srv/index.html
COPY wallpaper-gen.py /usr/local/bin/wallpaper-gen.py

COPY start.sh /start.sh
RUN chmod +x /start.sh \
    && python3 /usr/local/bin/wallpaper-gen.py /opt/wallpaper.png 1600 900

COPY supervisord.conf /etc/supervisor/supervisord.conf

EXPOSE 8080

CMD ["/start.sh"]
