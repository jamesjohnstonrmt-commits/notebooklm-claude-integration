"""
Google Drive file operations.

Handles:
- OAuth2 authentication with Google
- Downloading template files (PowerPoint / Word)
- Uploading generated output files
"""

from __future__ import annotations

import io
import logging
import os
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

logger = logging.getLogger(__name__)

# Scopes needed: read files (for templates) + write files (for uploads)
_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
]


class DriveHandler:
    """
    Thin wrapper around the Google Drive v3 API.

    Parameters
    ----------
    credentials_file:
        Path to the OAuth2 ``credentials.json`` downloaded from the
        Google Cloud Console (Desktop app flow).
    token_file:
        Path where the OAuth token cache will be stored.  Created
        automatically after the first interactive login.
    """

    def __init__(
        self,
        credentials_file: str = "credentials.json",
        token_file: str = "token.json",
    ) -> None:
        self.credentials_file = credentials_file
        self.token_file = token_file
        self._service: Any = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self) -> bool:
        """
        Perform OAuth2 authentication.

        On the very first run this opens a browser window so the user can
        grant permission.  Subsequent runs reuse the cached *token_file*.

        Returns True on success, False on failure.
        """
        creds: Credentials | None = None

        if os.path.exists(self.token_file):
            creds = Credentials.from_authorized_user_file(self.token_file, _SCOPES)

        # Refresh or re-authenticate if necessary
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Token refresh failed (%s) – re-authenticating.", exc)
                    creds = None

            if creds is None:
                if not os.path.exists(self.credentials_file):
                    logger.error(
                        "Google credentials file not found: %s\n"
                        "Download it from https://console.cloud.google.com/ "
                        "(APIs & Services → Credentials → Desktop app).",
                        self.credentials_file,
                    )
                    return False

                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, _SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Cache the token
            with open(self.token_file, "w") as fh:
                fh.write(creds.to_json())

        try:
            self._service = build("drive", "v3", credentials=creds)
            logger.info("Google Drive authenticated successfully.")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to build Drive service: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Download helpers
    # ------------------------------------------------------------------

    def download_file(self, file_id: str, dest_path: str) -> bool:
        """
        Export / download a file from Google Drive.

        Google Workspace files (Docs, Sheets, Slides) are *exported*;
        binary files (e.g. uploaded .pptx) are downloaded directly.

        Parameters
        ----------
        file_id:
            The Drive file ID (the long string in the shareable URL).
        dest_path:
            Local path where the downloaded bytes will be written.
        """
        if self._service is None:
            raise RuntimeError("Not authenticated – call authenticate() first.")

        # Determine the MIME type so we know how to export
        meta = (
            self._service.files()
            .get(fileId=file_id, fields="mimeType,name")
            .execute()
        )
        mime = meta.get("mimeType", "")
        name = meta.get("name", file_id)
        logger.info("Downloading '%s' (mime: %s)…", name, mime)

        # Map Google Workspace MIME types to export formats
        _export_map = {
            "application/vnd.google-apps.presentation": (
                "application/vnd.openxmlformats-officedocument"
                ".presentationml.presentation"
            ),
            "application/vnd.google-apps.document": (
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document"
            ),
            "application/vnd.google-apps.spreadsheet": (
                "application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet"
            ),
        }

        try:
            if mime in _export_map:
                request = self._service.files().export_media(
                    fileId=file_id,
                    mimeType=_export_map[mime],
                )
            else:
                request = self._service.files().get_media(fileId=file_id)

            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

            os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
            with open(dest_path, "wb") as fh:
                fh.write(buf.getvalue())

            logger.info("Saved to %s", dest_path)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to download file %r: %s", file_id, exc)
            return False

    # ------------------------------------------------------------------
    # Upload helpers
    # ------------------------------------------------------------------

    def upload_file(
        self,
        local_path: str,
        mime_type: str,
        drive_name: str | None = None,
        folder_id: str | None = None,
    ) -> str | None:
        """
        Upload a local file to Google Drive.

        Parameters
        ----------
        local_path:
            Path to the local file.
        mime_type:
            MIME type for the uploaded file (e.g.
            ``"application/vnd.openxmlformats-officedocument.presentationml.presentation"``).
        drive_name:
            File name as it will appear in Drive.  Defaults to the
            basename of *local_path*.
        folder_id:
            ID of the Drive folder to place the file in.  If ``None``,
            the file is placed in the root of My Drive.

        Returns
        -------
        str | None
            The Drive file ID of the newly created file, or ``None`` on
            failure.
        """
        if self._service is None:
            raise RuntimeError("Not authenticated – call authenticate() first.")

        name = drive_name or os.path.basename(local_path)
        metadata: dict[str, Any] = {"name": name}
        if folder_id:
            metadata["parents"] = [folder_id]

        media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
        try:
            result = (
                self._service.files()
                .create(body=metadata, media_body=media, fields="id,webViewLink")
                .execute()
            )
            file_id = result.get("id")
            link = result.get("webViewLink", "")
            logger.info("Uploaded '%s' → Drive ID: %s  (%s)", name, file_id, link)
            return file_id
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to upload %r: %s", local_path, exc)
            return None
