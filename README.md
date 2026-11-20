# postiz-tiktok-bridge

Publish the TikTok posts scheduled in [Postiz](https://github.com/gitroomhq/postiz-app) without an audited TikTok app.

Postiz needs TikTok's Direct Post audit to publish publicly. Without it, every post fails with
`App not approved for public posting`. This bridge runs next to Postiz, picks up those failed
TikTok posts, publishes them through the real TikTok Studio upload page (Playwright, with a browser
session saved by [autotok](https://github.com/makiisthenes/TiktokAutoUploader)'s login) and marks them as
published in the Postiz database.

## How it works

1. You schedule a TikTok post in Postiz as usual, with **Direct Post** as the posting method.
2. At the publish date, Postiz tries and fails (state `ERROR`).
3. After a grace period (`BRIDGE_GRACE_SECONDS`, 180 s by default), the bridge finds the post. It
   reads the video from the Postiz uploads volume and uploads it to TikTok with the caption and settings.
   The browser fills the caption and the privacy, checks both, then clicks Post.
4. The post is set to `PUBLISHED` in Postiz, with the TikTok video id. On failure it stays `ERROR`,
   with the bridge's error message.

Safety rules:
- Only posts with a publish date after `BRIDGE_SINCE` are touched. Older failed posts are never
  republished by surprise.
- A post is never retried after an upload was attempted (tracked in `data/bridge-state.json`), so no
  duplicates. To retry, delete its entry from that file.
- Privacy: `Public to everyone` posts go public. Every other level (followers, friends, only me)
  goes private (“Only you”). The bridge reads the privacy back from the page and refuses to post if it
  does not match. Same for the caption.
- Comment, duet, stitch and AI-label settings from Postiz are not applied: TikTok's defaults are used.
- Posts that Postiz delivered itself, with the **Upload** (inbox draft) method, are `PUBLISHED`
  and ignored.

## Requirements

- Postiz running with Docker Compose, with a local uploads volume (`STORAGE_PROVIDER=local`).
- A TikTok integration connected in Postiz.
- About 1.5 GB of RAM free during uploads (Chromium in a virtual display).

## Setup

```bash
git clone <this repo> postiz-tiktok-bridge && cd postiz-tiktok-bridge
cp .env.example .env
```

Fill in `.env`:

| Variable | What to put |
|---|---|
| `POSTIZ_NETWORK` | Docker network of the Postiz stack (`docker network ls`) |
| `POSTIZ_UPLOADS_VOLUME` | Postiz uploads volume (`docker volume ls`, the one mounted at `/uploads`) |
| `POSTIZ_DATABASE_URL` | Same value as `DATABASE_URL` in the Postiz container |
| `AUTOTOK_ACCOUNT` | Name for the saved TikTok session (any word) |
| `BRIDGE_SINCE` | Now, in ISO format (`2026-11-20T12:00:00Z`) |
| `BRIDGE_INTEGRATION_IDS` | Optional: comma-separated Postiz integration ids to handle |
| `TIKTOK_PROFILE_URL` | `https://www.tiktok.com/@yourhandle`, shown as the post link in Postiz |
| `BRIDGE_DRY_RUN` | `1` to only log what would be published |

Build the image:

```bash
docker compose build
```

### Log in to TikTok once

The login runs a real browser inside the container. You reach it through noVNC.

```bash
docker compose --profile login run --rm --service-ports login
```

On a remote server, open a tunnel first: `ssh -L 3010:127.0.0.1:3010 your-server`. Then open
<http://localhost:3010/vnc.html>, connect, and log in to TikTok in the browser window. The session is
saved to `data/accounts/<AUTOTOK_ACCOUNT>.json` and the container stops.

Do the same when TikTok logs the session out (uploads then fail with an auth error in Postiz).

### Start the bridge

```bash
docker compose up -d bridge
docker compose logs -f bridge
```

## Manual upload (CLI)

Through TikTok Studio, like the bridge (`False` = private):

```bash
docker compose --profile cli run --rm --entrypoint sh autotok -c 'Xvfb :99 & sleep 2; cd /app && python -c "
import studio, pathlib
print(studio.upload(pathlib.Path(\"/data/accounts/$AUTOTOK_ACCOUNT.json\"), pathlib.Path(\"/data/videos/x.mp4\"), \"caption\", False))"'
```

autotok's own API uploader is still in the image (`autotok upload -u <account> -v <file> -t <caption> -vi 1`),
but TikTok rejects its requests since 2026-11-20 (`status_code=5`).

## Notes

- autotok is only used for the login (session saved to `data/accounts/`). It is pinned to a commit
  (`AUTOTOK_REF` in the Dockerfile) and patched (`patches/patch_uploader.py`, upstream issue #141).
- Publishing drives TikTok Studio's page (`studio.py`). Selectors can break when TikTok changes the
  page: the bridge then fails safely (no post) with the error in Postiz. Automated posting may go
  against TikTok's terms. Use it on your own account, at your own risk.
- Resource limits are set in `docker-compose.yml`. Adjust them to your server.
