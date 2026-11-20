"""Postiz -> TikTok bridge.

Postiz cannot direct-post to TikTok without an audited app. This loop picks the
TikTok posts that Postiz failed to publish (or never tried), publishes them with
the TikTok Studio upload page (Playwright, saved autotok browser session) and writes the result back
into the Postiz database, so the post shows as published in the Postiz UI.

Safety:
- only posts whose publish date is after BRIDGE_SINCE are touched (old failed
  posts are never re-published by surprise);
- a post is marked in /data/bridge-state.json before the upload starts and is
  never retried automatically once an upload was attempted (no duplicates);
- PUBLIC_TO_EVERYONE posts go public, every other privacy level goes private.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import psycopg

log = logging.getLogger("bridge")

DB_URL = os.environ["POSTIZ_DATABASE_URL"]
UPLOADS_DIR = Path(os.environ.get("POSTIZ_UPLOADS_DIR", "/postiz-uploads")).resolve()
ACCOUNT = os.environ.get("AUTOTOK_ACCOUNT", "default")
SINCE = os.environ.get("BRIDGE_SINCE", "")
POLL = int(os.environ.get("BRIDGE_POLL_SECONDS", "60"))
# Postiz gets this long after the publish date to try (and fail) on its own.
GRACE = int(os.environ.get("BRIDGE_GRACE_SECONDS", "180"))
INTEGRATIONS = [i for i in os.environ.get("BRIDGE_INTEGRATION_IDS", "").split(",") if i]
PROFILE_URL = os.environ.get("TIKTOK_PROFILE_URL", "https://www.tiktok.com/tiktokstudio/content")
DRY_RUN = os.environ.get("BRIDGE_DRY_RUN", "0") == "1"
STATE_FILE = Path(os.environ.get("BRIDGE_STATE_FILE", "/data/bridge-state.json"))
VIDEO_EXT = (".mp4", ".mov", ".webm", ".m4v")

QUERY = """
select p.id, p.state, p."publishDate", p.content, p.image, p.settings
from "Post" p join "Integration" i on i.id = p."integrationId"
where i."providerIdentifier" = 'tiktok'
  and i.disabled = false and i."deletedAt" is null
  and p."deletedAt" is null and p."parentPostId" is null
  and p.state in ('QUEUE', 'ERROR')
  and p."publishDate" >= %(since)s
  and p."publishDate" <= %(due)s
  {integration_filter}
order by p."publishDate"
"""


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except FileNotFoundError:
        return {}


def save_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    tmp.replace(STATE_FILE)


def caption_from_html(content: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", content or "")
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:2200]


def video_path(image_json: str | None) -> Path:
    for media in json.loads(image_json or "[]"):
        url_path = urlparse(media.get("path", "")).path
        if not url_path.lower().endswith(VIDEO_EXT):
            continue
        rel = url_path.split("/uploads/", 1)[-1].lstrip("/")
        p = (UPLOADS_DIR / rel).resolve()
        if UPLOADS_DIR not in p.parents:
            raise ValueError(f"media path escapes the uploads dir: {url_path}")
        if not p.is_file():
            raise FileNotFoundError(f"video not found in uploads: {rel}")
        return p
    raise ValueError("post has no video")


def publish(row, client_factory) -> tuple[str, str]:
    post_id, _state, _date, content, image, settings_raw = row
    settings = json.loads(settings_raw or "{}")
    path = video_path(image)
    public = settings.get("privacy_level") == "PUBLIC_TO_EVERYONE"
    caption = caption_from_html(content)
    log.info("post %s: %s, %s, %d chars", post_id, path.name, "public" if public else "private", len(caption))
    if DRY_RUN:
        return "dry-run", PROFILE_URL
    video_id = client_factory()(path, caption, public)
    return video_id or "studio", PROFILE_URL


def tick(conn, state: dict, client_factory) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    filt = 'and p."integrationId" = any(%(ids)s)' if INTEGRATIONS else ""
    params = {"since": SINCE_DT, "due": now - timedelta(seconds=GRACE), "ids": INTEGRATIONS}
    with conn.cursor() as cur:
        cur.execute(QUERY.format(integration_filter=filt), params)
        rows = cur.fetchall()
    for row in rows:
        post_id = row[0]
        if post_id in state:
            continue
        state[post_id] = {"status": "uploading", "at": datetime.now(timezone.utc).isoformat()}
        save_state(state)
        try:
            video_id, url = publish(row, client_factory)
        except Exception as e:  # noqa: BLE001 - every failure is reported back to Postiz
            log.exception("post %s failed", post_id)
            state[post_id] = {"status": "failed", "error": str(e)[:500], "at": datetime.now(timezone.utc).isoformat()}
            save_state(state)
            if not DRY_RUN:
                with conn.cursor() as cur:
                    cur.execute('update "Post" set state = \'ERROR\', error = %s, "updatedAt" = now() where id = %s',
                                (json.dumps({"autotok": str(e)[:1000]}), post_id))
                conn.commit()
            continue
        state[post_id] = {"status": "published", "video_id": video_id, "at": datetime.now(timezone.utc).isoformat()}
        save_state(state)
        if not DRY_RUN:
            with conn.cursor() as cur:
                cur.execute('update "Post" set state = \'PUBLISHED\', "releaseId" = %s, "releaseURL" = %s, '
                            'error = null, "updatedAt" = now() where id = %s', (video_id, url, post_id))
            conn.commit()
        log.info("post %s published (%s)", post_id, video_id)


def main() -> int:
    global SINCE_DT
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not SINCE:
        log.error("BRIDGE_SINCE is required (ISO date, e.g. 2026-11-20T12:00:00Z): posts before it are ignored")
        return 2
    SINCE_DT = datetime.fromisoformat(SINCE.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    import studio

    account_file = Path(os.environ.get("AUTOTOK_ACCOUNTS_DIR", "/data/accounts")) / f"{ACCOUNT}.json"

    def client_factory():
        if not account_file.is_file():
            raise FileNotFoundError(f"no saved TikTok session at {account_file}: run the login service")
        return lambda path, caption, public: studio.upload(account_file, path, caption, public)

    log.info("bridge started: account=%s since=%s poll=%ss grace=%ss dry_run=%s", ACCOUNT, SINCE_DT, POLL, GRACE, DRY_RUN)
    state = load_state()
    once = "--once" in sys.argv
    while True:
        try:
            with psycopg.connect(DB_URL, connect_timeout=10) as conn:
                tick(conn, state, client_factory)
        except Exception:  # noqa: BLE001 - keep the loop alive across DB restarts
            log.exception("tick failed")
        if once:
            return 0
        time.sleep(POLL)


SINCE_DT: datetime
if __name__ == "__main__":
    sys.exit(main())
