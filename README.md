# OneSpan — Annotation Server

## Files

```
onespan/
├── server.py        # FastAPI server
├── index.html       # Annotation tool UI
├── requirements.txt # Python dependencies
├── dataset.json     # Created automatically on first run
└── README.md
```

## Quick start (JupyterLab terminal)

```bash
# 1. Install dependencies (once)
pip install -r requirements.txt

# 2. Start the server
python server.py
```

The server starts on **port 8765** by default.

## Accessing in Kubeflow / JupyterLab

JupyterLab proxies traffic through its own URL. Access the tool at:

```
https://<your-kubeflow-host>/user/<username>/proxy/8765/
```

Share that URL with annotators — everyone reads/writes the same `dataset.json`.

## Configuration

| Environment variable | Default        | Description                        |
|----------------------|----------------|------------------------------------|
| `PORT`               | `8765`         | Port to listen on                  |
| `DATA_FILE`          | `dataset.json` | Path to the persistent data file   |
| `HTML_FILE`          | `index.html`   | Path to the annotation tool HTML   |

```bash
# Example: custom port and data file
PORT=9000 DATA_FILE=/data/project_x.json python server.py
```

## How persistence works

- On **load**: the browser fetches `GET /data` and receives the full registry JSON
- On **save**: every annotation change POSTs `{ datasets, activeDatasetId }` to `/POST /data`
- Saves are **debounced** (600ms) so rapid typing doesn't flood the server
- Writes are **atomic**: data is written to a `.tmp` file then renamed, so a crash mid-write never corrupts `dataset.json`
- A **write lock** prevents concurrent saves from racing

## Keeping the server running

To keep the server alive after closing your terminal, use `nohup` or `screen`:

```bash
# Option A: nohup
nohup python server.py > onespan.log 2>&1 &
echo "Server PID: $!"

# Option B: screen
screen -S onespan
python server.py
# Ctrl+A, D to detach
```

## Backup

`dataset.json` is plain JSON — copy it anywhere to back up all annotations:

```bash
cp dataset.json dataset_backup_$(date +%Y%m%d).json
```
