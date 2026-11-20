#!/bin/sh
# Opens a visible Chromium on a virtual screen, served by noVNC on port 6080.
Xvfb :99 -screen 0 1280x900x24 >/tmp/xvfb.log 2>&1 &
sleep 1; fluxbox >/dev/null 2>&1 &
x11vnc -display :99 -forever -shared -nopw -localhost -rfbport 5900 >/tmp/vnc.log 2>&1 &
websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/ws.log 2>&1 &
sleep 2
exec autotok login -n "${AUTOTOK_ACCOUNT:-default}" --timeout 3600
