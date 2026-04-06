"""
NotebookLM → Claude → Presentation  |  CLI entry point

Usage
-----
    python main.py

The script guides you interactively through:
1. Connecting to NotebookLM (or entering content manually)
2. Selecting / confirming a notebook
3. Sending the content to Claude for slide generation
4. Downloading your PowerPoint and workbook templates from Google Drive
5. Populating the templates and saving the finished files locally
6. Uploading the finished files back to Google Drive
"""

from __future__ import annotations

import logging
import os
import sys
import textwrap

import config
from claude_generator import ClaudeGenerator
from drive_handler import DriveHandler
from notebooklm_handler import NotebookLMHandler
from presentation_builder import DOCX_MIME, PPTX_MIME, PresentationBuilder

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _banner() -> None:
    print(
        textwrap.dedent(
            """
            ╔══════════════════════════════════════════════════════╗
            ║   NotebookLM  →  Claude  →  Presentation Generator  ║
            ╚══════════════════════════════════════════════════════╝
            """
        )
    )


def _prompt(message: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{message}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return answer or default


def _confirm(message: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = _prompt(f"{message} [{hint}]")
    if not raw:
        return default
    return raw.lower() in ("y", "yes")


# ---------------------------------------------------------------------------
# Step 1 – NotebookLM
# ---------------------------------------------------------------------------

def step_notebooklm(handler: NotebookLMHandler) -> tuple[str, str]:
    """
    Connect to NotebookLM and let the user choose (or paste) content.

    Returns (notebook_title, notebook_text).
    """
    print("\n── Step 1 of 4: NotebookLM ─────────────────────────────")
    connected = handler.connect()

    if connected:
        notebooks = handler.list_notebooks()
        if notebooks:
            print(f"\nFound {len(notebooks)} notebook(s):\n")
            for i, nb in enumerate(notebooks, 1):
                print(f"  {i}. {nb['title']}")
            choice = _prompt(
                "\nEnter notebook number", default="1"
            )
            try:
                idx = int(choice) - 1
                selected = notebooks[idx]
            except (ValueError, IndexError):
                print("Invalid selection – using first notebook.")
                selected = notebooks[0]

            print(f"\nExporting: {selected['title']} …")
            nb_data = handler.get_notebook_data(selected["id"])
            if nb_data:
                return nb_data.title, nb_data.to_text()

    # Fallback – manual paste
    print(
        "\nNotebookLM SDK not available or no notebooks found.\n"
        "Please paste your notebook content below.\n"
        "Type/paste the text, then press Enter twice when done.\n"
    )
    title = _prompt("Notebook title", default="My Notebook")
    lines: list[str] = []
    prev_blank = False
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "" and prev_blank:
            break
        prev_blank = line == ""
        lines.append(line)
    text = "\n".join(lines).strip()
    if not text:
        print("No content provided. Exiting.")
        sys.exit(1)
    nb_data = NotebookLMHandler.from_text(title, text)
    return nb_data.title, nb_data.to_text()


# ---------------------------------------------------------------------------
# Step 2 – Claude content generation
# ---------------------------------------------------------------------------

def step_claude(notebook_text: str, notebook_title: str) -> object:
    """Send notebook content to Claude; return PresentationContent."""
    print("\n── Step 2 of 4: Generating content with Claude ─────────")
    num_slides = _prompt("How many slides to generate?", default="8")
    try:
        num_slides_int = int(num_slides)
    except ValueError:
        num_slides_int = 8

    generator = ClaudeGenerator(
        api_key=config.CLAUDE_API_KEY,
        model=config.CLAUDE_MODEL,
    )
    print("Sending to Claude…")
    content = generator.generate_presentation(
        notebook_text=notebook_text,
        num_slides=num_slides_int,
    )
    print(f"✓ Generated '{content.title}' with {len(content.slides)} slides.")
    return content


# ---------------------------------------------------------------------------
# Step 3 – Google Drive templates
# ---------------------------------------------------------------------------

def step_drive_download(drive: DriveHandler) -> tuple[str, str] | None:
    """
    Download the PowerPoint and workbook templates from Google Drive.

    Returns (pptx_path, docx_path) or None if Drive auth fails.
    """
    print("\n── Step 3 of 4: Downloading templates from Google Drive ─")

    if not os.path.exists(config.GOOGLE_CREDENTIALS_FILE):
        print(
            f"  Google credentials file not found: {config.GOOGLE_CREDENTIALS_FILE}\n"
            "  Skipping Drive download – templates must be provided locally.\n"
            "  Place your template files in the 'output/' directory and\n"
            "  re-run, or add credentials.json to enable Drive integration."
        )
        return None

    if not drive.authenticate():
        print("  Google Drive authentication failed. Skipping template download.")
        return None

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    pptx_path = os.path.join(config.OUTPUT_DIR, "template.pptx")
    docx_path = os.path.join(config.OUTPUT_DIR, "template.docx")

    ok1 = drive.download_file(config.PRESENTATION_TEMPLATE_ID, pptx_path)
    ok2 = drive.download_file(config.WORKBOOK_TEMPLATE_ID, docx_path)

    if ok1 and ok2:
        print("✓ Templates downloaded.")
        return pptx_path, docx_path

    print("  One or more templates could not be downloaded.")
    return None


# ---------------------------------------------------------------------------
# Step 4 – Build and upload
# ---------------------------------------------------------------------------

def step_build_and_upload(
    content: object,
    pptx_template: str,
    docx_template: str,
    drive: DriveHandler,
    drive_available: bool,
) -> None:
    """Populate templates and optionally upload results to Google Drive."""
    print("\n── Step 4 of 4: Building output files ───────────────────")
    builder = PresentationBuilder(output_dir=config.OUTPUT_DIR)

    pptx_out = builder.build_presentation(content, pptx_template)
    docx_out = builder.build_workbook(content, docx_template)

    print(f"✓ Presentation : {pptx_out}")
    print(f"✓ Workbook     : {docx_out}")

    if drive_available and _confirm("\nUpload finished files to Google Drive?"):
        folder = config.GOOGLE_DRIVE_FOLDER_ID or None
        drive.upload_file(pptx_out, PPTX_MIME, folder_id=folder)
        drive.upload_file(docx_out, DOCX_MIME, folder_id=folder)
        print("✓ Files uploaded to Google Drive.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    _banner()

    handler = NotebookLMHandler(
        email=config.NOTEBOOKLM_EMAIL,
        password=config.NOTEBOOKLM_PASSWORD,
    )
    drive = DriveHandler(
        credentials_file=config.GOOGLE_CREDENTIALS_FILE,
        token_file=config.GOOGLE_TOKEN_FILE,
    )

    # Step 1 – NotebookLM
    notebook_title, notebook_text = step_notebooklm(handler)

    # Step 2 – Claude
    content = step_claude(notebook_text, notebook_title)

    # Step 3 – Google Drive templates
    template_paths = step_drive_download(drive)
    drive_available = template_paths is not None

    if template_paths:
        pptx_template, docx_template = template_paths
    else:
        # Look for local fallback templates
        pptx_template = _prompt(
            "Path to local PowerPoint template (.pptx)",
            default=os.path.join(config.OUTPUT_DIR, "template.pptx"),
        )
        docx_template = _prompt(
            "Path to local Word template (.docx)",
            default=os.path.join(config.OUTPUT_DIR, "template.docx"),
        )
        if not os.path.exists(pptx_template) or not os.path.exists(docx_template):
            print(
                "\nTemplate files not found. Cannot build output.\n"
                "Please supply valid template paths and re-run."
            )
            sys.exit(1)

    # Step 4 – Build and upload
    step_build_and_upload(
        content=content,
        pptx_template=pptx_template,
        docx_template=docx_template,
        drive=drive,
        drive_available=drive_available,
    )

    print("\n✅  All done!\n")


if __name__ == "__main__":
    main()
