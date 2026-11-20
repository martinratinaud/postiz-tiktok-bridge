# One image for the three services: autotok CLI, noVNC login, Postiz bridge.
FROM python:3.12-slim-bookworm
ARG AUTOTOK_REPO=https://github.com/makiisthenes/TiktokAutoUploader.git
ARG AUTOTOK_REF=0bcbbdcff3600fbc09a47b9be107d1d3fd49b260
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright AUTOTOK_HOME=/data AUTOTOK_VIDEOS_DIR=/data/videos \
    AUTOTOK_BROWSER=local DISPLAY=:99
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates ffmpeg libatomic1 git xvfb x11vnc fluxbox novnc websockify \
    && ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html \
    && rm -rf /var/lib/apt/lists/*
COPY patches/patch_uploader.py /tmp/patch_uploader.py
RUN git clone "$AUTOTOK_REPO" /src && cd /src && git checkout "$AUTOTOK_REF" \
    && python /tmp/patch_uploader.py \
    && pip install ".[youtube]" "psycopg[binary]>=3.2" \
    && python -m playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/*
COPY bridge.py studio.py /app/
COPY scripts/ /app/scripts/
RUN chmod 755 /app/scripts/*.sh && useradd --create-home --uid 1000 autotok \
    && mkdir -p /data/videos && chown -R autotok:autotok /data
USER autotok
WORKDIR /data
ENTRYPOINT ["autotok"]
CMD ["--help"]
