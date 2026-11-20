import re
import json
from playwright.sync_api import sync_playwright
acct = json.load(open("/data/accounts/martin.json"))
with sync_playwright() as p:
    b = p.chromium.launch(headless=False, args=["--no-sandbox"])
    ctx = b.new_context(user_agent=acct.get("user_agent") or None, viewport={"width":1280,"height":900})
    ctx.add_cookies([{k:v for k,v in c.items() if k in ("name","value","domain","path","expires","httpOnly","secure","sameSite")} for c in acct["cookies"]])
    page = ctx.new_page()
    page.goto("https://www.tiktok.com/tiktokstudio/content", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(10000)
    page.evaluate("document.querySelectorAll('#react-joyride-portal').forEach(e=>e.remove())")
    assert "test" in page.inner_text("body")[:3000]
    page.mouse.click(1186,249)
    page.wait_for_timeout(1500)
    page.screenshot(path="/data/del1.png")
    d = page.get_by_text(re.compile(r"^Delete$"))
    print("delete items", d.count(), flush=True)
    d.last.click(force=True)
    page.wait_for_timeout(2000)
    page.screenshot(path="/data/del2.png")
    c = page.get_by_role("button", name=re.compile("^Delete$"))
    print("confirm", c.count(), flush=True)
    c.last.click(force=True)
    page.wait_for_timeout(5000)
    page.reload(); page.wait_for_timeout(10000)
    page.evaluate("document.querySelectorAll('#react-joyride-portal').forEach(e=>e.remove())")
    page.screenshot(path="/data/content.png")
    b.close()
