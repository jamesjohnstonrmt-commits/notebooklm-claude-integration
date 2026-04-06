# notebooklm-claude-integration

Integration tool that connects **NotebookLM** research notebooks to **Claude** for automatic presentation creation.

## What it does

1. Connects to your NotebookLM account and exports a notebook's sources & notes.
2. Sends the content to Claude (Anthropic API) to generate structured slide content.
3. Downloads your PowerPoint and workbook templates from Google Drive.
4. Populates the templates with the generated content.
5. Saves the finished `.pptx` and `.docx` files locally and uploads them back to Google Drive.

## Project structure

```
.
├── main.py                  # Interactive CLI entry point
├── notebooklm_handler.py    # NotebookLM SDK integration
├── claude_generator.py      # Claude API content generation
├── presentation_builder.py  # PowerPoint & Word template population
├── drive_handler.py         # Google Drive file operations
├── config.py                # Configuration (reads from .env)
├── requirements.txt         # Python dependencies
└── .env.example             # Template for environment variables
```

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure credentials

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Required values:

| Variable | Description |
|---|---|
| `CLAUDE_API_KEY` | Your Anthropic API key |
| `NOTEBOOKLM_EMAIL` | Google account email used for NotebookLM |
| `NOTEBOOKLM_PASSWORD` | Google account password |
| `GOOGLE_CREDENTIALS_FILE` | Path to OAuth2 `credentials.json` from Google Cloud Console |

### 3. Google Cloud credentials

To enable Google Drive integration:
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable the **Google Drive API**
3. Create an OAuth 2.0 Desktop client → download `credentials.json`
4. Place `credentials.json` in the project root

### 4. Run

```bash
python main.py
```

The CLI will guide you through each step interactively.

## Templates

The integration uses two Google Drive templates:

- **Presentation template** (PowerPoint): `1UoX6n6ajp9BxtzxgsHgdA078vwz2IOyi`
- **Workbook template** (Word): `1v9so1qGI932W2858qW28jJe75S0fD0pL`

These IDs are pre-configured in `config.py` and can be overridden via environment variables.

## Running without NotebookLM SDK

If the `notebooklm` package is unavailable or authentication fails, the tool falls back to a manual-input mode where you can paste notebook content directly into the terminal.

