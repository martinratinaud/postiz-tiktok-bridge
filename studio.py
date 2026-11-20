"""Publish a video through the real TikTok Studio upload page (Playwright).

TikTok's private web API changes often (autotok's direct API call started failing
with status_code=5 on 2026-11-20). Driving the upload page lets TikTok's own web
app build the request. The saved autotok session (cookies + user agent) is reused.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("bridge.studio")

UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=webapp"
POST_BUTTON = 'button[data-e2e="post_video_button"]'
PRIVACY_COMBO = '[data-e2e="video_visibility_container"] button[role="combobox"]'
COOKIE_KEYS = ("name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite")


class StudioError(RuntimeError):
    pass


def _dismiss_overlays(page) -> None:
    # onboarding tours and tip popups ("Use these sounds...") cover the Post button
    page.evaluate("""() => {
        document.querySelectorAll('#react-joyride-portal').forEach(e => e.remove());
        document.querySelectorAll('[data-floating-ui-portal]').forEach(e => {
            if (e.querySelector('.modal-desc')) e.remove();
        });
    }""")
    cancel = page.get_by_role("button", name="Cancel", exact=True)
    if cancel.count() and cancel.first.is_visible():
        cancel.first.click()


def _set_caption(page, caption: str) -> None:
    editor = page.locator('[contenteditable="true"]').first
    editor.click()
    page.keyboard.press("ControlOrMeta+A")
    page.keyboard.press("Backspace")
    for i, line in enumerate(caption.split("\n")):
        if i:
            page.keyboard.press("Shift+Enter")
        if line:
            page.keyboard.insert_text(line)
    page.wait_for_timeout(1000)
    # a hashtag/mention suggestion list may stay open after the last word
    page.mouse.click(5, 5)
    got = re.sub(r"\s+", " ", editor.inner_text()).strip()
    if got != re.sub(r"\s+", " ", caption).strip():
        raise StudioError(f"caption not set correctly (editor shows {got[:80]!r}): not posting")


def _set_privacy(page, public: bool) -> None:
    want = "Everyone" if public else "Only you"
    combo = page.locator(PRIVACY_COMBO)
    if combo.inner_text().strip() != want:
        combo.click(force=True)
        page.locator('[role="listbox"] [role="option"]').filter(has_text=want).first.click()
        page.wait_for_timeout(800)
    got = combo.inner_text().strip()
    if got != want:
        raise StudioError(f"privacy is '{got}', expected '{want}': not posting")


def upload(account_file: Path, video: Path, caption: str, public: bool, timeout_s: int = 300) -> str:
    """Publish and return the TikTok item id (or '' if TikTok did not return one)."""
    from playwright.sync_api import sync_playwright

    acct = json.loads(account_file.read_text())
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--no-sandbox"])
        try:
            ctx = browser.new_context(user_agent=acct.get("user_agent") or None,
                                      viewport={"width": 1280, "height": 900})
            ctx.add_cookies([{k: v for k, v in c.items() if k in COOKIE_KEYS} for c in acct["cookies"]])
            page = ctx.new_page()
            page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(8000)
            if "login" in page.url:
                raise StudioError("TikTok session expired: log in again (docker compose --profile login ...)")
            page.set_input_files('input[type="file"]', str(video))
            button = page.locator(POST_BUTTON)
            for _ in range(timeout_s // 2):
                page.wait_for_timeout(2000)
                _dismiss_overlays(page)
                if button.count() and button.first.get_attribute("aria-disabled") in (None, "false"):
                    break
            else:
                raise StudioError("video still processing after timeout")
            _dismiss_overlays(page)
            _set_caption(page, caption)
            _dismiss_overlays(page)
            _set_privacy(page, public)
            _dismiss_overlays(page)
            with page.expect_response(re.compile(r".*/project/post/v1/.*"), timeout=120000) as resp_info:
                button.first.click()
                # TikTok sometimes asks to confirm (content check still running)
                for _ in range(10):
                    page.wait_for_timeout(1500)
                    confirm = page.get_by_role("button", name=re.compile(r"^Post( now)?$"))
                    if confirm.count() > 1 and confirm.last.is_visible():
                        confirm.last.click()
                        break
            body = resp_info.value.text()
            try:
                data = json.loads(body)
            except ValueError:
                raise StudioError(f"unexpected TikTok response: {body[:300]}") from None
            if data.get("status_code") not in (0, None):
                raise StudioError(f"TikTok rejected the post: {data.get('status_msg')} (status_code={data.get('status_code')})")
            m = re.search(r'"item_id"\s*:\s*"?(\d+)', body)
            page.wait_for_timeout(3000)
            return m.group(1) if m else ""
        finally:
            browser.close()
