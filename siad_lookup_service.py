#!/usr/bin/env python3
"""
SIAD Dossier Lookup Service (v2 -- real browser typing, raw output only)

- Receives HA ID/Password and NL ID/Password in one request
- For EACH of them (HA first, then NL):
    1. Opens a real headless browser
    2. Navigates to https://siadreg.mspas.gob.gt/consulta/
    3. Types the ID into "Ingrese SIAD No." and the password into
       "Ingrese llave de consulta." (exactly like a human would)
    4. Clicks "Enviar"
    5. Waits until the actual results table has rendered (not just "page
       loaded" -- this site is slow, and grabbing the page too early
       returns the still-blank form)
    6. Captures the FULL resulting page as raw HTML (no parsing --
       that's done downstream in n8n)
    7. Also takes a full-page screenshot
- Returns both HA and NL results together in one response, as raw
  HTML + screenshot only.
"""

import base64
import os
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright

# ===================== CONFIG =====================
PORT = int(os.environ.get("PORT", 5001))
SIAD_URL = "https://siadreg.mspas.gob.gt/consulta/"
SCREENSHOT_DIR = os.environ.get("SCREENSHOT_DIR", "/app/screenshots")
NAV_TIMEOUT_MS = 30000
RESULTS_WAIT_TIMEOUT_MS = 20000
# ==================================================

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
app = Flask(__name__)


def scrape_one(page, siad_id, query_key, label):
    """Type the given ID/key into the live form, submit, wait for real
    results, and return the full raw HTML + screenshot. No parsing."""

    page.goto(SIAD_URL, wait_until="load", timeout=NAV_TIMEOUT_MS)

    page.fill('input[name="TextBox1"]', "")
    page.fill('input[name="TextBox1"]', str(siad_id))
    page.fill('input[name="txtLlaveConsulta"]', "")
    page.fill('input[name="txtLlaveConsulta"]', str(query_key))

    page.click('input[name="Button1"]')

    try:
        page.wait_for_selector("text=EXPEDIENTE", timeout=RESULTS_WAIT_TIMEOUT_MS)
    except Exception:
        page.wait_for_timeout(3000)

    html = page.content()
    screenshot_bytes = page.screenshot(full_page=True)

    screenshot_path = os.path.join(SCREENSHOT_DIR, f"{label}_{siad_id}.png")
    with open(screenshot_path, "wb") as f:
        f.write(screenshot_bytes)

    return {
        "success": True,
        "html": html,
        "screenshotPath": screenshot_path,
        "screenshotBase64": base64.b64encode(screenshot_bytes).decode("utf-8"),
    }


def run_lookup(ha_id, ha_key, nl_id, nl_key):
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
        page = browser.new_page()

        ha_result = scrape_one(page, ha_id, ha_key, "ha")
        nl_result = scrape_one(page, nl_id, nl_key, "nl")

        browser.close()

    return {"ha": ha_result, "nl": nl_result}


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "running"}), 200


@app.route("/lookup", methods=["POST"])
def lookup_endpoint():
    """Original single-lookup endpoint, kept for backward compatibility.
    Body: {"id": "...", "key": "..."}"""
    try:
        data = request.get_json()
        if not data or "id" not in data or "key" not in data:
            return jsonify({"success": False, "error": "Both 'id' and 'key' are required"}), 400

        siad_id = str(data["id"]).strip()
        query_key = str(data["key"]).strip()
        print(f"\nLooking up SIAD ID: {siad_id}")

        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
            page = browser.new_page()
            result = scrape_one(page, siad_id, query_key, "single")
            browser.close()

        return jsonify(result), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/lookup-both", methods=["POST"])
def lookup_both_endpoint():
    """New combined endpoint: does HA first, then NL, in one browser session.
    Body: {"haId": "...", "haKey": "...", "nlId": "...", "nlKey": "..."}
    Returns raw HTML + screenshot for each -- no field parsing."""
    try:
        data = request.get_json()
        required = ["haId", "haKey", "nlId", "nlKey"]
        if not data or any(k not in data for k in required):
            return jsonify({
                "success": False,
                "error": f"All of {required} are required"
            }), 400

        ha_id = str(data["haId"]).strip()
        ha_key = str(data["haKey"]).strip()
        nl_id = str(data["nlId"]).strip()
        nl_key = str(data["nlKey"]).strip()

        print(f"\nLooking up HA: {ha_id}  |  NL: {nl_id}")

        result = run_lookup(ha_id, ha_key, nl_id, nl_key)
        return jsonify(result), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    print(f"SIAD Lookup Service (v2) — Port {PORT}")
    print(f"Screenshots saved to: {SCREENSHOT_DIR}\n")
    app.run(host="0.0.0.0", port=PORT, debug=False)
