#!/usr/bin/env python3
"""
SIAD Dossier Lookup Service
- Looks up a dossier on the Guatemala MSPAS SIAD site using a real headless browser
- Fills in the SIAD No. and query key, submits, reads back the result
- Extracts all header fields + the current status (latest movement's ESTADO)
- Saves + returns a full-page screenshot of the result
- Exposes a simple Flask API (/health, /lookup) so n8n (or anything else) can call it
"""

import asyncio
import base64
import os
import re
from flask import Flask, request, jsonify
from playwright.async_api import async_playwright

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


class SiadLookup:
    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        self.page = await self.browser.new_page()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.browser.close()
        await self.playwright.stop()

    async def lookup(self, siad_id, query_key):
        await self.page.goto(SIAD_URL, wait_until="networkidle", timeout=30000)

        await self.page.fill('input[name="TextBox1"]', str(siad_id))
        await self.page.fill('input[name="txtLlaveConsulta"]', str(query_key))

        await asyncio.gather(
            self.page.wait_for_load_state("networkidle", timeout=30000),
            self.page.click('input[name="Button1"]'),
        )

        html = await self.page.content()
        screenshot_bytes = await self.page.screenshot(full_page=True)

        fields = {key: extract_field(html, label) for key, label in FIELD_LABELS}
        movement = extract_current_status(html)
        found = bool(fields.get("expediente"))

        screenshot_path = os.path.join(SCREENSHOT_DIR, f"{siad_id}.png")
        with open(screenshot_path, "wb") as f:
            f.write(screenshot_bytes)

        return {
            "success": True,
            "found": found,
            "fields": fields,
            "currentStatus": movement["status"] if movement else None,
            "lastMovement": movement,
            "screenshotPath": screenshot_path,
            "screenshotBase64": base64.b64encode(screenshot_bytes).decode("utf-8"),
        }


async def run_lookup(siad_id, query_key):
    async with SiadLookup() as lookup:
        return await lookup.lookup(siad_id, query_key)


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

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(run_lookup(siad_id, query_key))
        loop.close()

        return jsonify(result), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    print(f"SIAD Lookup Service — Port {PORT}")
    print(f"Screenshots saved to: {SCREENSHOT_DIR}\n")
    app.run(host="0.0.0.0", port=PORT, debug=False)
