"""
OneSpan annotation server — proxy-hardened edition.

Works correctly behind:
  - JupyterLab / Kubeflow proxy
  - Corporate HTTP proxies
  - Nginx / Traefik reverse proxies

Usage:
    pip install -r requirements.txt
    python server.py

Environment variables:
    PORT       Port to listen on          (default: 8765)
    DATA_FILE  Path to JSON data file     (default: dataset.json)
    HTML_FILE  Path to the tool HTML      (default: index.html)
    ROOT_PATH  ASGI root path if behind   (default: "")
               a sub-path proxy, e.g.
               /user/alice/proxy/8765
"""

import json
import os
import shutil
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PORT      = int(os.environ.get("PORT", 8765))
DATA_FILE = Path(os.environ.get("DATA_FILE", "dataset.json"))
HTML_FILE = Path(os.environ.get("HTML_FILE", "index.html"))
ROOT_PATH = os.environ.get("ROOT_PATH", "")   # set if proxy doesn't strip prefix

_save_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DATA_FILE.exists():
        DATA_FILE.write_text(
            json.dumps({"datasets": [], "activeDatasetId": None}, indent=2),
            encoding="utf-8",
        )
        print(f"[onespan] Created data file: {DATA_FILE.resolve()}")
    else:
        print(f"[onespan] Data file:  {DATA_FILE.resolve()}")
    print(f"[onespan] HTML file:  {HTML_FILE.resolve()}")
    print(f"[onespan] Listening:  http://0.0.0.0:{PORT}/")
    print(f"[onespan] Health:     http://localhost:{PORT}/health")
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="OneSpan", root_path=ROOT_PATH, lifespan=lifespan)

# Permissive CORS — required when accessed through any proxy
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_data() -> dict:
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot read data file: {e}")


async def _write_data(body: dict) -> None:
    """Atomic write under a lock — safe against concurrent requests."""
    async with _save_lock:
        try:
            tmp = DATA_FILE.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(body, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            shutil.move(str(tmp), str(DATA_FILE))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Cannot write data file: {e}")


async def _parse_body(request: Request) -> dict:
    """
    Parse request body as JSON regardless of Content-Type header.
    Corporate proxies sometimes strip or mangle Content-Type, so we
    attempt JSON parsing on the raw bytes rather than relying on the header.
    """
    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty request body")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")


# ---------------------------------------------------------------------------
# Routes — all registered with and without trailing slash
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
@app.get("", response_class=HTMLResponse)
async def serve_ui():
    """Serve the annotation tool HTML."""
    if not HTML_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail=f"index.html not found at {HTML_FILE.resolve()}",
        )
    return HTMLResponse(content=HTML_FILE.read_text(encoding="utf-8"))


@app.get("/data")
@app.get("/data/")
async def get_data():
    """Return the full annotation state."""
    return JSONResponse(content=_read_data())


@app.post("/data")
@app.post("/data/")
async def save_data(request: Request):
    """
    Persist annotation state.
    Accepts JSON regardless of Content-Type (proxy-safe).
    """
    body = await _parse_body(request)

    if not isinstance(body, dict) or "datasets" not in body:
        raise HTTPException(
            status_code=400,
            detail='Body must be a JSON object containing a "datasets" key',
        )

    await _write_data(body)

    return JSONResponse({
        "ok": True,
        "savedAt": datetime.now(timezone.utc).isoformat(),
        "datasetCount": len(body.get("datasets", [])),
    })


@app.get("/health")
async def health():
    """
    Health check — open this in a browser to confirm the server is reachable
    and its files are in place.
    """
    return {
        "status": "ok",
        "port": PORT,
        "dataFile": str(DATA_FILE.resolve()),
        "dataFileExists": DATA_FILE.exists(),
        "htmlFile": str(HTML_FILE.resolve()),
        "htmlFileExists": HTML_FILE.exists(),
        "rootPath": ROOT_PATH or "(none)",
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        proxy_headers=True,      # trust X-Forwarded-* headers from proxy
        forwarded_allow_ips="*", # accept forwarded headers from any proxy IP
    )
