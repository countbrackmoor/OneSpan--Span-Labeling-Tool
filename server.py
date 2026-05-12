"""
OneSpan annotation server.
Serves the tool HTML and persists all annotation data to dataset.json.

Usage:
    pip install -r requirements.txt
    python server.py

    # Or with a custom port / data file:
    DATA_FILE=my_data.json PORT=8888 python server.py

JupyterLab / Kubeflow:
    Run this in a terminal within your JupyterLab environment.
    The server will be reachable at your notebook's proxy URL, e.g.:
    https://<your-kubeflow-host>/user/<username>/proxy/8765/
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

# Write lock — prevents concurrent saves from corrupting the file
_save_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Lifespan: ensure data file exists
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DATA_FILE.exists():
        DATA_FILE.write_text(json.dumps({"datasets": [], "activeDatasetId": None}, indent=2))
        print(f"[onespan] Created empty data file: {DATA_FILE}")
    else:
        print(f"[onespan] Using existing data file: {DATA_FILE}")
    print(f"[onespan] Serving on http://localhost:{PORT}/")
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="OneSpan", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the annotation tool HTML."""
    if not HTML_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail=f"UI file not found: {HTML_FILE}. "
                   f"Make sure index.html is in the same directory as server.py."
        )
    return HTMLResponse(content=HTML_FILE.read_text(encoding="utf-8"))


@app.get("/data")
async def get_data():
    """Return the full annotation state."""
    try:
        content = DATA_FILE.read_text(encoding="utf-8")
        return JSONResponse(content=json.loads(content))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read data: {e}")


@app.post("/data")
async def save_data(request: Request):
    """
    Persist the full annotation state.
    Writes atomically: new data → temp file → rename.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Basic sanity check
    if not isinstance(body, dict) or "datasets" not in body:
        raise HTTPException(status_code=400, detail="Expected {datasets, activeDatasetId}")

    async with _save_lock:
        try:
            tmp = DATA_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
            shutil.move(str(tmp), str(DATA_FILE))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to write data: {e}")

    return JSONResponse({"ok": True, "savedAt": datetime.now(timezone.utc).isoformat()})


@app.get("/health")
async def health():
    return {"status": "ok", "dataFile": str(DATA_FILE), "htmlFile": str(HTML_FILE)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)
