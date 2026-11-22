"""Drive the lab web (Armonía on 127.0.0.1:18480, fictitious user «ana») with Playwright for screenshots and checks.

Usage: python web.py <script.py>   — the script gets `page(width)`, `shot(pg, name)` and `LAB` in its globals.
Only the lab: never point this at the real installation.
"""
import sys
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/lab"))
from lab import APP_PORT, PASSWORD, USER

LAB = f"http://127.0.0.1:{APP_PORT}"
SHOTS = ROOT / "runtime/capturas"
SHOTS.mkdir(parents=True, exist_ok=True)


def main(script):
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("ARMONIA_CHROMIUM"))
        contexts = {}

        def page(width=390, height=844):
            if width not in contexts:
                ctx = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=2 if width < 600 else 1,
                                          has_touch=width < 600, is_mobile=width < 600, locale="es-ES")
                pg = ctx.new_page()
                pg.goto(LAB)
                pg.locator('input[type=password], #view').first.wait_for()
                if pg.locator("input[type=password]").count():
                    pg.locator("input").first.fill(USER)
                    pg.locator("input[type=password]").fill(PASSWORD)
                    pg.locator("button[type=submit], form button").first.click()
                pg.wait_for_selector("#view", timeout=15000)
                contexts[width] = pg
            return contexts[width]

        def shot(pg, name):
            pg.wait_for_timeout(600)
            pg.screenshot(path=str(SHOTS / f"{name}.png"))

        exec(Path(script).read_text(), {"page": page, "shot": shot, "LAB": LAB})
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1])
