from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8010"
OUT = Path("data") / "screens"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        errors: list[str] = []
        page.on("console", lambda msg: errors.append(f"console:{msg.type}:{msg.text}") if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(f"pageerror:{exc}"))
        for path, name in [
            ("/", "overview"),
            ("/models", "models"),
            ("/stt", "stt"),
            ("/tts", "tts"),
            ("/voices", "voices"),
            ("/queue", "queue"),
            ("/history", "history"),
            ("/settings", "settings"),
            ("/system", "system"),
            ("/monitor", "monitor"),
        ]:
            page.goto(BASE + path, wait_until="networkidle")
            page.wait_for_timeout(700)
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
            print("shot", path, page.title())
        print("ERRORS", errors[:30])
        browser.close()


if __name__ == "__main__":
    main()
