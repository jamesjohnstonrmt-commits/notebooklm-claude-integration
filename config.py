"""
Configuration for the NotebookLM → Claude → Presentation integration.

Sensitive values (API keys, credentials) should be set via environment
variables or a .env file – never committed to source control.
"""

import os
from dotenv import load_dotenv

# Load .env file when present (ignored if it does not exist)
load_dotenv()

# ---------------------------------------------------------------------------
# Claude / Anthropic
# ---------------------------------------------------------------------------
CLAUDE_API_KEY: str = os.environ.get("CLAUDE_API_KEY", "your-claude-api-key-here")
CLAUDE_MODEL: str = os.environ.get("CLAUDE_MODEL", "claude-opus-4-5")

# ---------------------------------------------------------------------------
# NotebookLM
# ---------------------------------------------------------------------------
NOTEBOOKLM_EMAIL: str = os.environ.get("NOTEBOOKLM_EMAIL", "your-google-email@gmail.com")
NOTEBOOKLM_PASSWORD: str = os.environ.get("NOTEBOOKLM_PASSWORD", "your-google-password")

# ---------------------------------------------------------------------------
# Google Drive / OAuth
# ---------------------------------------------------------------------------
# Path to the OAuth2 credentials JSON file downloaded from Google Cloud Console
GOOGLE_CREDENTIALS_FILE: str = os.environ.get(
    "GOOGLE_CREDENTIALS_FILE", "credentials.json"
)
# OAuth token cache (created automatically after first login)
GOOGLE_TOKEN_FILE: str = os.environ.get("GOOGLE_TOKEN_FILE", "token.json")

# Google Drive folder where generated files will be saved
GOOGLE_DRIVE_FOLDER_ID: str = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")

# Google Drive file IDs for the templates
PRESENTATION_TEMPLATE_ID: str = os.environ.get(
    "PRESENTATION_TEMPLATE_ID", "1UoX6n6ajp9BxtzxgsHgdA078vwz2IOyi"
)
WORKBOOK_TEMPLATE_ID: str = os.environ.get(
    "WORKBOOK_TEMPLATE_ID", "1v9so1qGI932W2858qW28jJe75S0fD0pL"
)

# ---------------------------------------------------------------------------
# Output defaults
# ---------------------------------------------------------------------------
OUTPUT_DIR: str = os.environ.get("OUTPUT_DIR", "output")
