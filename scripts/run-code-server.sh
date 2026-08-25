#!/bin/sh
# code-server launcher.
# IMPORTANT: code-server honours $PORT over --bind-addr, which collides
# with the public HTTP server port on Railway - so we unset it here and
# pin code-server to an internal localhost port instead.
unset PORT
CODE_PORT="${CODE_SERVER_PORT:-8443}"
exec code-server \
    --bind-addr "127.0.0.1:${CODE_PORT}" \
    --auth none \
    --disable-telemetry \
    --disable-update-check
