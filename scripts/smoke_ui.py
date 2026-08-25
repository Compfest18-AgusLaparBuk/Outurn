from pathlib import Path
import re

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "clear"


def main() -> None:
    browser_errors: list[str] = []
    console_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: browser_errors.append(str(error)))
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )

        page.goto("http://127.0.0.1:3000", wait_until="domcontentloaded", timeout=60_000)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            # Next dev keeps a hot-reload connection open; the DOM is still ready.
            page.wait_for_timeout(1_000)
        assert page.get_by_role("heading", name="Check a shipment before dispatch").is_visible()
        assert page.get_by_role("heading", name="Shipment intake").is_visible()
        assert page.get_by_role("heading", name="Document collection").is_visible()
        assert page.get_by_text("Dashboard", exact=True).count() == 0
        assert page.locator(".shipment-sidebar").count() == 1

        page.get_by_label("Shipment reference").fill("SHP-CLEAR-001")
        page.get_by_label("Expected origin").fill("Jakarta")
        page.get_by_label("Expected destination").fill("Bandung")
        file_inputs = page.locator("input[type='file']")
        file_inputs.nth(0).set_input_files(str(SAMPLE / "surat-jalan.pdf"))
        file_inputs.nth(1).set_input_files(str(SAMPLE / "invoice.pdf"))
        file_inputs.nth(2).set_input_files(str(SAMPLE / "packing-list.pdf"))
        for index in range(3):
            file_inputs.nth(index).dispatch_event("change")

        analyze = page.get_by_role("button", name="Analyze shipment")
        assert analyze.is_enabled(), page.locator(".shipment-action-bar").inner_text()
        analyze.click()
        page.get_by_role("heading", name="Cross-document reconciliation").wait_for(timeout=60_000)
        assert page.get_by_role("heading", name="Explainable shipment risk").is_visible()
        assert page.get_by_role("heading", name="Destination verification").is_visible()
        assert page.get_by_role("heading", name=re.compile("dispatch", re.IGNORECASE)).count() > 0

        evidence_toggle = page.get_by_role("switch", name="Show evidence details")
        evidence_toggle.click()
        assert page.get_by_text("Raw:", exact=False).count() > 0

        recheck = page.get_by_role("button", name="Re-check shipment")
        assert recheck.is_enabled()
        recheck.click()
        page.get_by_role("heading", name="What changed?").wait_for(timeout=60_000)
        assert not browser_errors, browser_errors
        assert not console_errors, console_errors
        print("UI smoke passed: intake -> upload -> analysis -> evidence -> re-check -> before/after")
        browser.close()


if __name__ == "__main__":
    main()
