"""
NotebookLM web scraper using Selenium.

Authenticates with Google and scrapes notebook data from
https://notebooklm.google.com/ without requiring the unofficial SDK.

Falls back gracefully when Selenium or Chrome/ChromeDriver is unavailable.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_NOTEBOOKLM_URL = "https://notebooklm.google.com/"
_WAIT_TIMEOUT = 20  # seconds

_NOTEBOOKLM_HOST = "notebooklm.google.com"
_GOOGLE_ACCOUNTS_HOST = "accounts.google.com"


def _url_hostname(url: str) -> str:
    """Return the hostname of *url*, lower-cased."""
    return (urlparse(url).hostname or "").lower()


def _is_google_login_url(url: str) -> bool:
    """True when *url* is on the Google accounts sign-in domain."""
    host = _url_hostname(url)
    return host == _GOOGLE_ACCOUNTS_HOST


def _is_notebooklm_url(url: str) -> bool:
    """True when *url* is on the NotebookLM domain."""
    return _url_hostname(url) == _NOTEBOOKLM_HOST


class NotebookLMScraper:
    """
    Selenium-based scraper for NotebookLM.

    Usage::

        scraper = NotebookLMScraper(email="you@gmail.com", password="secret")
        if scraper.login():
            notebooks = scraper.list_notebooks()
            # [{"id": "...", "title": "..."}, ...]
            data = scraper.get_notebook_content("notebook-id")
            # {"id": "...", "title": "...", "content": "..."}
        scraper.close()

    If Selenium or Chrome is unavailable, :meth:`login` returns ``False``
    and no exception is raised – the caller should fall back to manual input.
    """

    def __init__(self, email: str = "", password: str = "") -> None:
        self.email = email
        self._password = password
        self._driver: Any = None
        self._logged_in = False

    # ------------------------------------------------------------------
    # Driver setup
    # ------------------------------------------------------------------

    def _create_driver(self) -> Any:
        """
        Create a headless Chrome/Chromium WebDriver.

        Raises ``ImportError`` if *selenium* is not installed.
        Raises ``RuntimeError`` if no compatible browser is found.
        """
        from selenium import webdriver  # type: ignore[import]
        from selenium.webdriver.chrome.options import Options  # type: ignore[import]
        from selenium.webdriver.chrome.service import Service  # type: ignore[import]

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1280,800")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        try:
            # webdriver-manager can auto-download the matching ChromeDriver
            from webdriver_manager.chrome import ChromeDriverManager  # type: ignore[import]

            service = Service(ChromeDriverManager().install())
            return webdriver.Chrome(service=service, options=options)
        except ImportError:
            pass

        # Fall back to ChromeDriver already on PATH
        return webdriver.Chrome(options=options)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def login(self) -> bool:
        """
        Open NotebookLM and sign in with Google credentials.

        Returns ``True`` on success, ``False`` on any failure (no exception
        is raised so callers can degrade gracefully).
        """
        try:
            self._driver = self._create_driver()
        except ImportError:
            logger.warning(
                "selenium package not found. "
                "Install it with: pip install selenium\n"
                "Falling back to manual-input mode."
            )
            return False
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not start browser for NotebookLM scraper: %s", exc)
            return False

        try:
            return self._do_login()
        except Exception as exc:  # noqa: BLE001
            logger.warning("NotebookLM login failed: %s", exc)
            return False

    def _do_login(self) -> bool:
        from selenium.webdriver.common.by import By  # type: ignore[import]
        from selenium.webdriver.support import expected_conditions as EC  # type: ignore[import]
        from selenium.webdriver.support.ui import WebDriverWait  # type: ignore[import]

        wait = WebDriverWait(self._driver, _WAIT_TIMEOUT)

        logger.info("Navigating to NotebookLM…")
        self._driver.get(_NOTEBOOKLM_URL)
        time.sleep(2)

        current = self._driver.current_url
        if _is_google_login_url(current) or "signin" in current.lower():
            logger.info("Redirected to Google login – submitting credentials…")
            if not self._fill_google_login(wait):
                return False

        # Wait until we land (back) on notebooklm.google.com
        try:
            wait.until(lambda d: _is_notebooklm_url(d.current_url))
            # Wait for at least one notebook card or the "new notebook" button
            wait.until(
                EC.any_of(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "[data-notebook-id]")
                    ),
                    EC.presence_of_element_located((By.CSS_SELECTOR, "mat-card")),
                    EC.presence_of_element_located(
                        (By.XPATH, '//*[contains(@class,"notebook")]')
                    ),
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, 'button[aria-label="New notebook"]')
                    ),
                )
            )
            self._logged_in = True
            logger.info("Logged in to NotebookLM successfully.")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Timed out waiting for NotebookLM home page: %s", exc)
            if _is_notebooklm_url(self._driver.current_url):
                self._logged_in = True
                return True
            return False

    def _fill_google_login(self, wait: Any) -> bool:
        """Fill in the Google email → Next → password → Next sign-in flow."""
        from selenium.webdriver.common.by import By  # type: ignore[import]
        from selenium.webdriver.common.keys import Keys  # type: ignore[import]
        from selenium.webdriver.support import expected_conditions as EC  # type: ignore[import]

        try:
            # ── Email ────────────────────────────────────────────────────────
            email_input = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[type="email"]'))
            )
            email_input.clear()
            email_input.send_keys(self.email)
            email_input.send_keys(Keys.RETURN)
            time.sleep(1.5)

            # ── Password ─────────────────────────────────────────────────────
            password_input = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[type="password"]'))
            )
            password_input.clear()
            password_input.send_keys(self._password)
            self._password = ""  # clear from memory immediately
            password_input.send_keys(Keys.RETURN)
            time.sleep(2)

            # If Google requires 2-FA / additional verification we cannot proceed
            parsed = urlparse(self._driver.current_url)
            url_path = (parsed.path or "").lower()
            url_host = (parsed.hostname or "").lower()
            if "challenge" in url_path or url_path.endswith("/2fa") or (
                url_host == _GOOGLE_ACCOUNTS_HOST and "checkpoint" in url_path
            ):
                logger.warning(
                    "Google 2-step verification required. "
                    "The scraper cannot complete login automatically."
                )
                return False

            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fill Google login form: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Notebook listing
    # ------------------------------------------------------------------

    def list_notebooks(self) -> list[dict[str, Any]]:
        """
        Return a list of notebooks from the NotebookLM home page.

        Each entry: ``{"id": "...", "title": "..."}``.
        Returns an empty list on any failure.
        """
        if not self._logged_in or self._driver is None:
            return []

        try:
            return self._scrape_notebook_list()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to list notebooks: %s", exc)
            return []

    def _scrape_notebook_list(self) -> list[dict[str, Any]]:
        from selenium.webdriver.common.by import By  # type: ignore[import]

        # Ensure we are on the home page
        if not _is_notebooklm_url(self._driver.current_url) or (
            urlparse(self._driver.current_url).path.strip("/") != ""
        ):
            self._driver.get(_NOTEBOOKLM_URL)
            time.sleep(2)

        notebooks: list[dict[str, Any]] = []

        # ── Strategy 1: explicit data-notebook-id attributes ────────────────
        cards = self._driver.find_elements(
            By.CSS_SELECTOR, "[data-notebook-id]"
        )
        if cards:
            for card in cards:
                nb_id = card.get_attribute("data-notebook-id") or ""
                title = (
                    card.get_attribute("aria-label")
                    or card.text.strip().split("\n")[0]
                    or "Untitled"
                )
                if nb_id:
                    notebooks.append({"id": nb_id, "title": title})
            if notebooks:
                return notebooks

        # ── Strategy 2: anchor tags containing /notebook/<ID> ───────────────
        links = self._driver.find_elements(
            By.CSS_SELECTOR, 'a[href*="/notebook/"]'
        )
        if links:
            seen: set[str] = set()
            for link in links:
                href = link.get_attribute("href") or ""
                parts = href.rstrip("/").split("/notebook/")
                if len(parts) == 2:
                    nb_id = parts[1].split("?")[0].strip()
                    if nb_id and nb_id not in seen:
                        title = (
                            link.text.strip()
                            or link.get_attribute("aria-label")
                            or "Untitled"
                        )
                        if not title or title == "Untitled":
                            try:
                                title = (
                                    link.find_element(By.XPATH, "..").text.strip()
                                    or "Untitled"
                                )
                            except Exception:  # noqa: BLE001
                                pass
                        notebooks.append({"id": nb_id, "title": title})
                        seen.add(nb_id)
            if notebooks:
                return notebooks

        # ── Strategy 3: generic card/list elements (index-based IDs) ────────
        for selector in (
            "mat-card",
            ".notebook-card",
            '[class*="notebook-card"]',
            '[class*="NoteCard"]',
        ):
            cards = self._driver.find_elements(By.CSS_SELECTOR, selector)
            if cards:
                for i, card in enumerate(cards):
                    title = card.text.strip().split("\n")[0] or f"Notebook {i + 1}"
                    notebooks.append({"id": f"index:{i}", "title": title})
                logger.warning(
                    "Using index-based notebook IDs – content fetching may not work."
                )
                return notebooks

        logger.warning("Could not find any notebooks on the NotebookLM home page.")
        return []

    # ------------------------------------------------------------------
    # Notebook content
    # ------------------------------------------------------------------

    def get_notebook_content(self, notebook_id: str) -> dict[str, Any] | None:
        """
        Navigate to *notebook_id* and extract its text content.

        Returns ``{"id": ..., "title": ..., "content": ...}`` or ``None``.
        """
        if not self._logged_in or self._driver is None:
            return None

        try:
            return self._scrape_notebook_content(notebook_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch notebook %r: %s", notebook_id, exc)
            return None

    def _scrape_notebook_content(self, notebook_id: str) -> dict[str, Any] | None:
        from selenium.webdriver.common.by import By  # type: ignore[import]
        from selenium.webdriver.support import expected_conditions as EC  # type: ignore[import]
        from selenium.webdriver.support.ui import WebDriverWait  # type: ignore[import]

        if notebook_id.startswith("index:"):
            logger.warning(
                "Cannot fetch content for index-based notebook ID %r – "
                "direct URL navigation is not possible.",
                notebook_id,
            )
            return None

        url = f"{_NOTEBOOKLM_URL.rstrip('/')}/notebook/{notebook_id}"
        logger.info("Navigating to notebook: %s", url)
        self._driver.get(url)

        wait = WebDriverWait(self._driver, _WAIT_TIMEOUT)
        try:
            wait.until(
                EC.any_of(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, '[class*="source"]')
                    ),
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, '[class*="note"]')
                    ),
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "notebook-source-list")
                    ),
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, '[class*="NotesPanel"]')
                    ),
                    EC.presence_of_element_located((By.TAG_NAME, "main")),
                )
            )
        except Exception:  # noqa: BLE001
            pass  # page loaded but expected panel not found – still try to extract

        time.sleep(1.5)  # let dynamic content settle

        # ── Title ────────────────────────────────────────────────────────────
        title = "Untitled Notebook"
        for sel in ("h1", '[class*="title"]', '[class*="NotebookTitle"]'):
            els = self._driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                t = els[0].text.strip()
                if t and t.lower() != "notebooklm":
                    title = t
                    break

        # ── Content ──────────────────────────────────────────────────────────
        text_parts: list[str] = []
        seen_text: set[str] = set()
        content_selectors = [
            '[class*="source-content"]',
            '[class*="SourceContent"]',
            '[class*="note-content"]',
            '[class*="NoteContent"]',
            "notebook-source",
            '[class*="source-item"]',
            "main",
        ]
        for sel in content_selectors:
            elements = self._driver.find_elements(By.CSS_SELECTOR, sel)
            for el in elements:
                text = el.text.strip()
                if text and text not in seen_text and len(text) > 10:
                    text_parts.append(text)
                    seen_text.add(text)
            if text_parts:
                break

        if not text_parts:
            # Last resort: capture all visible body text
            body_text = self._driver.find_element(By.TAG_NAME, "body").text.strip()
            if body_text:
                text_parts = [body_text]

        content = "\n\n".join(text_parts)
        return {"id": notebook_id, "title": title, "content": content}

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Quit the browser driver and release resources."""
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:  # noqa: BLE001
                pass
            self._driver = None
        self._logged_in = False
