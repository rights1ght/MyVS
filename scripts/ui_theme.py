from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8010"
OUT = Path("data/screens")


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(BASE + "/models", wait_until="networkidle")
        if page.locator("html.dark").count() == 0:
            page.locator('button[title="Тёмная тема"]').click()
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / "models-dark.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(BASE + "/", wait_until="networkidle")
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / "overview-mobile.png"), full_page=True)
        browser.close()


if __name__ == "__main__":
    main()
