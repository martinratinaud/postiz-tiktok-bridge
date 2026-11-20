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
    page.screenshot(path="/data/content.png")
    b.close()
