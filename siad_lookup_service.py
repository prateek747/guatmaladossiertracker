#!/usr/bin/env python3
"""
SIAD Dossier Lookup Service
- Looks up a dossier on the Guatemala MSPAS SIAD site
- Uses direct HTTP requests (ASP.NET VIEWSTATE handshake) to reliably fetch
  the result page -- this avoids timing races that occur when driving a
  live browser against this particular (fairly slow) government site
- Extracts all header fields + the current status (latest movement's ESTADO)
- Renders the fetched HTML in a headless browser purely to capture a
  full-page screenshot (no live navigation/timing issues, since the HTML
  is already final)
- Exposes a simple Flask API (/health, /lookup) so n8n (or anything else)
  can call it
"""

import base64
import os
import re
import requests
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright

# ===================== CONFIG =====================
PORT = int(os.environ.get("PORT", 5001))
SIAD_URL = "https://siadreg.mspas.gob.gt/consulta/"
SCREENSHOT_DIR = os.environ.get("SCREENSHOT_DIR", "/app/screenshots")
# ==================================================

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
app = Flask(__name__)

# Fields shown on the SIAD result page, in the order they appear.
FIELD_LABELS = [
    ("expediente", "EXPEDIENTE"),
    ("documento", "DOCUMENTO DE REFERENCIA"),
    ("fechaDocumento", "FECHA DE DOCUMENTO"),
    ("asunto", "ASUNTO"),
    ("unidadAdministrativa", "UNIDAD ADMINISTRATIVA"),
    ("entidad", "ENTIDAD"),
    ("marginado", "MARGINADO"),
    ("descripcion", "DESCRIPCION"),
    ("folios", "FOLIOS"),
    ("remitente", "REMITENTE"),
    ("observaciones", "OBSERVACIONES"),
    ("fechaCreacion", "FECHA CREACION"),
    ("fechaUltimoMovimiento", "FECHA ULTIMO MOVIMIENTO"),
]


def extract_field(html, label):
    pattern = r"<strong>\s*" + label + r"\s*:?\s*</strong>\s*<span[^>]*>([^<]*)</span>"
    m = re.search(pattern, html, re.IGNORECASE)
    return m.group(1).strip() if m else None


def extract_current_status(html):
    # Movement rows: NO | FECHA | ACTUAL | FOLIOS | OBSERVACIONES | MARGINADO | ENVIADO | ESTADO
    # Rows are listed most-recent-first, so the first match is the current status.
    row_pattern = (
        r"<tr>\s*<td>\s*<span[^>]*>(\d+)</span>\s*</td>"
        r"<td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td>"
        r"<td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td>\s*</tr>"
    )
    rows = re.findall(row_pattern, html)
    if not rows:
        return None
    first = rows[0]
    return {
        "status": first[7].strip(),
        "lastMovementDate": first[1].strip(),
        "from": first[5].strip(),
        "to": first[2].strip(),
    }


def get_viewstate_tokens():
    """GET the form page and extract the ASP.NET VIEWSTATE handshake fields + session cookie."""
    resp = requests.get(SIAD_URL, timeout=30)
    html = resp.text

    def get_val(field_id):
        m = re.search(r'id="' + field_id + r'"\s+value="([^"]*)"', html)
        return m.group(1) if m else ""

    return {
        "viewstate": get_val("__VIEWSTATE"),
        "viewstategenerator": get_val("__VIEWSTATEGENERATOR"),
        "eventvalidation": get_val("__EVENTVALIDATION"),
        "cookies": resp.cookies,
    }


def fetch_result_html(siad_id, query_key):
    """Reliably fetch the SIAD result page HTML via direct HTTP POST (no browser)."""
    tokens = get_viewstate_tokens()
    payload = {
        "__VIEWSTATE": tokens["viewstate"],
        "__VIEWSTATEGENERATOR": tokens["viewstategenerator"],
        "__EVENTVALIDATION": tokens["eventvalidation"],
        "TextBox1": str(siad_id),
        "txtLlaveConsulta": str(query_key),
        "Button1": "Enviar",
    }
    resp = requests.post(
        SIAD_URL, data=payload, cookies=tokens["cookies"], timeout=30
    )
    return resp.text


def render_screenshot(html, siad_id):
    """Render already-fetched HTML in a headless browser purely to screenshot it."""
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
        page = browser.new_page()
        page.set_content(html, wait_until="load")
        screenshot_bytes = page.screenshot(full_page=True)
        browser.close()

    screenshot_path = os.path.join(SCREENSHOT_DIR, f"{siad_id}.png")
    with open(screenshot_path, "wb") as f:
        f.write(screenshot_bytes)

    return screenshot_bytes, screenshot_path


def run_lookup(siad_id, query_key):
    html = fetch_result_html(siad_id, query_key)

    fields = {key: extract_field(html, label) for key, label in FIELD_LABELS}
    movement = extract_current_status(html)
    found = bool(fields.get("expediente"))

    screenshot_bytes, screenshot_path = render_screenshot(html, siad_id)

    return {
        "success": True,
        "found": found,
        "fields": fields,
        "currentStatus": movement["status"] if movement else None,
        "lastMovement": movement,
        "screenshotPath": screenshot_path,
        "screenshotBase64": base64.b64encode(screenshot_bytes).decode("utf-8"),
    }


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "running"}), 200


@app.route("/lookup", methods=["POST"])
def lookup_endpoint():
    try:
        data = request.get_json()
        if not data or "id" not in data or "key" not in data:
            return jsonify({"success": False, "error": "Both 'id' and 'key' are required"}), 400

        siad_id = str(data["id"]).strip()
        query_key = str(data["key"]).strip()
        print(f"\nLooking up SIAD ID: {siad_id}")

        result = run_lookup(siad_id, query_key)
        return jsonify(result), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    print(f"SIAD Lookup Service — Port {PORT}")
    print(f"Screenshots saved to: {SCREENSHOT_DIR}\n")
    app.run(host="0.0.0.0", port=PORT, debug=False)