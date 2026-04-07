"""
Flask web interface for the NotebookLM → Claude → Presentation Generator.

Usage
-----
    python app.py

Then open http://localhost:5000 in your browser.

All existing backend modules (NotebookLMHandler, ClaudeGenerator,
DriveHandler, PresentationBuilder) are reused unchanged.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from typing import Any

from flask import Flask, jsonify, render_template, request, send_from_directory

import config
from claude_generator import ClaudeGenerator
from drive_handler import DriveHandler
from notebooklm_handler import NotebookLMHandler
from presentation_builder import DOCX_MIME, PPTX_MIME, PresentationBuilder

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# In-memory job store: { job_id: { "status": ..., "progress": ...,
#                                   "files": [...], "error": ... } }
# NOTE: Job state is not persisted – all in-progress jobs are lost on server
# restart.  This is intentional for this single-user local tool.
_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Routes – HTML
# ---------------------------------------------------------------------------


@app.route("/")
def index() -> str:
    """Serve the main web interface."""
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes – API
# ---------------------------------------------------------------------------


@app.route("/api/notebooks")
def api_notebooks():
    """Return a JSON list of available NotebookLM notebooks."""
    handler = NotebookLMHandler(
        email=config.NOTEBOOKLM_EMAIL,
        password=config.NOTEBOOKLM_PASSWORD,
    )
    connected = handler.connect()
    if not connected:
        return jsonify({"notebooks": [], "warning": "NotebookLM not available – SDK not installed or authentication failed."})

    notebooks = handler.list_notebooks()
    return jsonify({"notebooks": notebooks})


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """
    Start a generation job in a background thread.

    Expected JSON body::

        {
          "notebook_id": "...",   // required
          "num_slides": 8         // optional, default 8
        }

    Returns::

        { "job_id": "<uuid>" }
    """
    data = request.get_json(force=True, silent=True) or {}
    notebook_id: str = data.get("notebook_id", "").strip()
    num_slides: int = int(data.get("num_slides", 8))

    if not notebook_id:
        return jsonify({"error": "notebook_id is required"}), 400

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "queued",
            "progress": "Starting…",
            "files": [],
            "error": None,
        }

    thread = threading.Thread(
        target=_run_generation,
        args=(job_id, notebook_id, num_slides),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def api_status(job_id: str):
    """Return the current status of a generation job."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/download/<path:filename>")
def download_file(filename: str):
    """Serve a generated file for download."""
    output_dir = os.path.abspath(config.OUTPUT_DIR)
    # Prevent path traversal – only allow files strictly inside output_dir
    target = os.path.abspath(os.path.join(output_dir, filename))
    if not target.startswith(output_dir + os.sep):
        return jsonify({"error": "Forbidden"}), 403
    return send_from_directory(output_dir, filename, as_attachment=True)


# ---------------------------------------------------------------------------
# Background job worker
# ---------------------------------------------------------------------------


def _set_progress(job_id: str, status: str, progress: str) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = status
            _jobs[job_id]["progress"] = progress


def _run_generation(job_id: str, notebook_id: str, num_slides: int) -> None:
    """Full generation pipeline; updates _jobs[job_id] throughout."""
    try:
        # ── Step 1: Fetch notebook content ──────────────────────────────────
        _set_progress(job_id, "running", "Connecting to NotebookLM…")

        handler = NotebookLMHandler(
            email=config.NOTEBOOKLM_EMAIL,
            password=config.NOTEBOOKLM_PASSWORD,
        )
        connected = handler.connect()

        if connected:
            _set_progress(job_id, "running", "Fetching notebook content…")
            nb_data = handler.get_notebook_data(notebook_id)
            if nb_data is None:
                _fail(job_id, f"Could not retrieve notebook '{notebook_id}' from NotebookLM.")
                return
            notebook_title = nb_data.title
            notebook_text = nb_data.to_text()
        else:
            _fail(job_id, "NotebookLM is not available. Please ensure the SDK is installed and your credentials are correct.")
            return

        # ── Step 2: Generate content with Claude ────────────────────────────
        _set_progress(job_id, "running", f"Generating {num_slides} slides with Claude…")

        generator = ClaudeGenerator(
            api_key=config.CLAUDE_API_KEY,
            model=config.CLAUDE_MODEL,
        )
        content = generator.generate_presentation(
            notebook_text=notebook_text,
            num_slides=num_slides,
        )
        logger.info("Claude generated '%s' (%d slides).", content.title, len(content.slides))

        # ── Step 3: Download templates from Google Drive ────────────────────
        _set_progress(job_id, "running", "Downloading templates from Google Drive…")

        drive = DriveHandler(
            credentials_file=config.GOOGLE_CREDENTIALS_FILE,
            token_file=config.GOOGLE_TOKEN_FILE,
        )
        pptx_template, docx_template, drive_authenticated = _get_templates(drive)

        # ── Step 4: Build output files ───────────────────────────────────────
        _set_progress(job_id, "running", "Building PowerPoint and Word documents…")

        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        builder = PresentationBuilder(output_dir=config.OUTPUT_DIR)
        pptx_out = builder.build_presentation(content, pptx_template)
        docx_out = builder.build_workbook(content, docx_template)

        # ── Step 5: Upload to Google Drive (optional) ────────────────────────
        if drive_authenticated:
            _set_progress(job_id, "running", "Uploading files to Google Drive…")
            folder = config.GOOGLE_DRIVE_FOLDER_ID or None
            drive.upload_file(pptx_out, PPTX_MIME, folder_id=folder)
            drive.upload_file(docx_out, DOCX_MIME, folder_id=folder)

        # Collect downloadable files
        files = []
        output_dir = os.path.abspath(config.OUTPUT_DIR)
        for path in (pptx_out, docx_out):
            if path and os.path.exists(path):
                rel = os.path.relpath(path, output_dir)
                files.append({
                    "filename": rel,
                    "label": _download_label(path),
                })

        # Also collect any podcast script if present
        for fname in os.listdir(config.OUTPUT_DIR):
            if fname.endswith(".txt") and "podcast" in fname.lower():
                files.append({
                    "filename": fname,
                    "label": f"🎙 Podcast Script ({fname})",
                })

        with _jobs_lock:
            _jobs[job_id]["status"] = "complete"
            _jobs[job_id]["progress"] = "Generation complete!"
            _jobs[job_id]["files"] = files
            _jobs[job_id]["title"] = content.title

    except ValueError as exc:
        logger.error("Generation job %s: invalid input – %s", job_id, exc)
        _fail(job_id, f"Configuration or input error: {exc}")
    except RuntimeError as exc:
        logger.error("Generation job %s: runtime error – %s", job_id, exc)
        _fail(job_id, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Generation job %s failed unexpectedly.", job_id)
        _fail(job_id, f"Unexpected error: {exc}")


def _fail(job_id: str, message: str) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["progress"] = message
            _jobs[job_id]["error"] = message


def _get_templates(drive: DriveHandler) -> tuple[str, str, bool]:
    """
    Download templates from Drive if possible, otherwise look for local files.

    Returns (pptx_template_path, docx_template_path, drive_authenticated).
    Raises RuntimeError if no templates can be found.
    """
    pptx_path = os.path.join(config.OUTPUT_DIR, "template.pptx")
    docx_path = os.path.join(config.OUTPUT_DIR, "template.docx")

    if os.path.exists(config.GOOGLE_CREDENTIALS_FILE) and drive.authenticate():
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        ok1 = drive.download_file(config.PRESENTATION_TEMPLATE_ID, pptx_path)
        ok2 = drive.download_file(config.WORKBOOK_TEMPLATE_ID, docx_path)
        if ok1 and ok2:
            return pptx_path, docx_path, True

    # Fall back to local templates
    if os.path.exists(pptx_path) and os.path.exists(docx_path):
        return pptx_path, docx_path, False

    raise RuntimeError(
        "Template files not found. "
        "Please ensure Google Drive credentials are configured, "
        "or place template.pptx and template.docx in the output/ directory."
    )


def _download_label(path: str) -> str:
    """Return a human-friendly label for a download link."""
    name = os.path.basename(path)
    if name.endswith(".pptx"):
        return f"📊 PowerPoint ({name})"
    if name.endswith(".docx"):
        return f"📝 Word Workbook ({name})"
    return f"📄 {name}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, host="0.0.0.0", port=5000)
