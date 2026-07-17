# SIAD Lookup Service

Looks up a dossier on the Guatemala MSPAS SIAD site
(`https://siadreg.mspas.gob.gt/consulta/`) using a real headless browser
(Playwright), and returns:

- All structured header fields (Expediente, Documento, Fecha, Asunto, etc.)
- The current status (most recent movement's `ESTADO`)
- A full-page screenshot of the result, base64-encoded (and also saved to
  disk under `screenshots/`)

Runs as a small Flask API, fully containerized — no manual Python/Playwright
setup needed on the server, just Docker.

## Deploy (first time, on a new server)

```bash
git clone <your-repo-url>
cd siad-lookup-service
docker compose up -d --build
```

That's it. This builds the image (based on Microsoft's official Playwright
Python image, which already includes the Chromium browser — no extra
downloads needed) and runs it in the background, restarting automatically
if the server reboots.

## Deploy (updating later)

```bash
cd siad-lookup-service
git pull
docker compose up -d --build
```

## Verify it's running

```bash
curl http://localhost:5001/health
# {"status":"running"}
```

## Usage

**POST** `http://<your-server>:5001/lookup`

Request body:
```json
{ "id": "250147", "key": "UD3ZCX" }
```

Response:
```json
{
  "success": true,
  "found": true,
  "fields": {
    "expediente": "250147",
    "documento": "ESPECIALIDAD FARMACEUTICA MULTIORIGEN",
    "fechaDocumento": "4/12/2025",
    "asunto": "NUEVO REGISTRO SANITARIO",
    "unidadAdministrativa": "RECEPCION DE EXPEDIENTE Y MUESTRA",
    "entidad": "RECEPCION DE EXPEDIENTE Y MUESTRA",
    "marginado": "NUEVO",
    "descripcion": "TRIAMCINOLONA ACETONIDO RHYDBURG 40 MG/ML SUSPENSION INYECTABLE",
    "folios": "1",
    "remitente": "MEDICAMENTOS",
    "observaciones": "NUEVO REGISTRO",
    "fechaCreacion": "4/12/2025",
    "fechaUltimoMovimiento": "5/12/2025"
  },
  "currentStatus": "RECEPCION EXPEDIENTE CONFIRMADA",
  "lastMovement": {
    "status": "RECEPCION EXPEDIENTE CONFIRMADA",
    "lastMovementDate": "5/12/2025 00:00:00",
    "from": "NUEVO",
    "to": "SECRETARIA AUTORIZACIONES SANITARIAS"
  },
  "screenshotPath": "/app/screenshots/250147.png",
  "screenshotBase64": "iVBORw0KGgoAAAANSUhEUgAA..."
}
```

If the ID/key combination doesn't match any record, `found` will be `false`
and `fields`/`currentStatus` will be `null`.

Test it directly:
```bash
curl -X POST http://localhost:5001/lookup \
  -H "Content-Type: application/json" \
  -d '{"id":"250147","key":"UD3ZCX"}'
```

## Calling it from n8n

Plain **HTTP Request** node — once for the NL fields, once for the HA
fields:
- Method: `POST`
- URL: `http://localhost:5001/lookup` (or `http://siad-lookup-service:5001/lookup`
  if n8n and this container share a Docker network — see the commented-out
  `networks` section in `docker-compose.yml`)
- Body (JSON): `{ "id": "{{ $json.nlId }}", "key": "{{ $json.nlPass }}" }`

To turn `screenshotBase64` into an actual image file/attachment in n8n, add
a **Convert to File** node after this call.

## Notes

- Each request launches a fresh, isolated browser instance — safe for
  concurrent NL + HA lookups running in parallel.
- Timeout is 30 seconds per navigation.
- Screenshots persist on the host in `./screenshots/` thanks to the Docker
  volume mount, even if the container restarts.
- No credentials, tokens, or paid third-party accounts required.
