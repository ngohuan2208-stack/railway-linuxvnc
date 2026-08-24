FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:1 \
    VNC_PORT=5901 \
    LANG=C.UTF-8 \
    LANGUAGE=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    xfce4 xfce4-terminal thunar \
    tigervnc-standalone-server tigervnc-common tigervnc-tools \
    novnc websockify \
    dbus-x11 xdg-utils \
    bash git curl wget nano \
    python3 python3-pip \
    procps \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /root/.vnc && \
    echo '#!/bin/sh\n\
unset SESSION_MANAGER\n\
unset DBUS_SESSION_BUS_ADDRESS\n\
exec startxfce4' > /root/.vnc/xstartup && \
    chmod +x /root/.vnc/xstartup

RUN mkdir -p /home/user && \
    useradd -m -d /home/user -s /bin/bash user && \
    chown -R user:user /home/user

COPY start.sh /start.sh
RUN chmod +x /start.sh

COPY supervisord.conf /etc/supervisor/supervisord.conf

EXPOSE 8080

CMD ["/start.sh"]
