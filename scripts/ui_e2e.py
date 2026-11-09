from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
WAV = Path(os.environ.get("MYVS_TEST_WAV", "data/test.wav"))


def main() -> None:
    if not WAV.exists():
        raise SystemExit("Set MYVS_TEST_WAV=/path/to/short.wav before running this smoke test.")
    Path("data/screens").mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(BASE + "/stt", wait_until="networkidle")
        page.locator('input[type="file"]').set_input_files(str(WAV))
        page.wait_for_timeout(500)
        page.get_by_role("button", name="Транскрибировать").click()
        page.wait_for_selector("text=Готово", timeout=120000)
        page.wait_for_timeout(1000)
        text = page.locator("textarea").input_value()
        print("STT TEXT:", text[:200])
        page.screenshot(path="data/screens/e2e-stt.png", full_page=True)

        page.goto(BASE + "/tts", wait_until="networkidle")
        page.get_by_role("button", name="Синтезировать").click()
        page.wait_for_selector("audio", timeout=120000)
        page.wait_for_timeout(500)
        print("TTS audio:", page.locator("audio").count())
        page.screenshot(path="data/screens/e2e-tts.png", full_page=True)
        print("ERRORS", errors)
        browser.close()


if __name__ == "__main__":
    main()
