"""Confluence API client for hooks module.

Centralized Confluence client with PAT authentication, rate limiting, and
full page/attachment operations.

Usage:
    from hooks.integrations.confluence import ConfluenceClient

    client = ConfluenceClient.get_client()
    page = client.create_page("Title", "# Markdown content", parent_id="123")
    print(page.url)
"""

import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests

from hooks.common import log

# =============================================================================
# CONFIGURATION
# =============================================================================

# Rate limiting (Confluence allows ~10 req/sec)
MIN_REQUEST_INTERVAL = 0.1  # 100ms between requests
MAX_RETRIES = 3

# Language mapping for code blocks
LANGUAGE_MAP = {
    "py": "python",
    "python": "python",
    "tf": "terraform",
    "js": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    "sh": "bash",
    "bash": "bash",
    "shell": "bash",
    "json": "json",
    "html": "html",
    "xml": "xml",
    "css": "css",
    "java": "java",
    "c": "c",
    "cpp": "cpp",
    "csharp": "csharp",
    "go": "go",
    "rust": "rust",
    "sql": "sql",
    "yaml": "yaml",
    "yml": "yaml",
    "dockerfile": "dockerfile",
    "ruby": "ruby",
    "php": "php",
    "swift": "swift",
    "kotlin": "kotlin",
    "scala": "scala",
}


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class PageInfo:
    """Information about a Confluence page."""

    id: str
    title: str
    space_key: str
    url: str
    version: int = 1


# =============================================================================
# CONFLUENCE CLIENT
# =============================================================================


class ConfluenceClient:
    """Centralized Confluence API client with rate limiting and retry logic."""

    _instance: Optional["ConfluenceClient"] = None

    def __init__(
        self,
        base_url: str,
        token: str,
        space_key: str = "",
        default_parent_id: str = "",
    ):
        """
        Initialize Confluence client.

        Args:
            base_url: Confluence server URL
            token: Personal Access Token (PAT)
            space_key: Default space key
            default_parent_id: Default parent page ID
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.space_key = space_key
        self.default_parent_id = default_parent_id

        # Create authenticated session
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

        # Rate limiting
        self._last_request_time = 0.0

    @classmethod
    def get_client(cls) -> "ConfluenceClient":
        """
        Get singleton client instance configured from environment variables.

        Environment variables:
            CONFLUENCE_SERVER_URL - Base URL (required)
            CONFLUENCE_TOKEN - PAT token (required)
            CONFLUENCE_SPACE_KEY - Default space key (optional)
            PARENT_PAGE_ID - Default parent page ID (optional)

        Returns:
            Configured ConfluenceClient instance

        Raises:
            ValueError: If required environment variables are missing
        """
        if cls._instance is not None:
            return cls._instance

        base_url = os.environ.get("CONFLUENCE_SERVER_URL", "").rstrip("/")
        token = os.environ.get("CONFLUENCE_TOKEN", "")
        space_key = os.environ.get("CONFLUENCE_SPACE_KEY", "")
        parent_id = os.environ.get("PARENT_PAGE_ID", "")

        missing = []
        if not base_url:
            missing.append("CONFLUENCE_SERVER_URL")
        if not token:
            missing.append("CONFLUENCE_TOKEN")

        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

        cls._instance = cls(base_url, token, space_key, parent_id)
        log(
            "ConfluenceClient: Initialized",
            {"base_url": base_url, "space_key": space_key},
        )
        return cls._instance

    @classmethod
    def clear_instance(cls) -> None:
        """Clear singleton instance (useful for testing)."""
        cls._instance = None

    # =========================================================================
    # REQUEST HANDLING
    # =========================================================================

    def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def _make_request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> requests.Response:
        """
        Make HTTP request with rate limiting and retry logic.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            url: Request URL
            **kwargs: Additional arguments for requests

        Returns:
            Response object

        Raises:
            requests.RequestException: If request fails after retries
        """
        self._rate_limit()

        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.request(method, url, **kwargs)

                # Handle rate limiting response
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    log("ConfluenceClient: Rate limited", {"retry_after": retry_after})
                    time.sleep(retry_after)
                    continue

                if response.status_code not in (200, 201, 204):
                    log(
                        "ConfluenceClient: API error",
                        {
                            "status": response.status_code,
                            "response": response.text[:500],
                        },
                    )

                response.raise_for_status()
                return response

            except requests.exceptions.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    wait_time = 2**attempt  # Exponential backoff
                    log(
                        "ConfluenceClient: Request failed, retrying",
                        {
                            "attempt": attempt + 1,
                            "wait": wait_time,
                            "error": str(e),
                        },
                    )
                    time.sleep(wait_time)
                else:
                    raise

        raise RuntimeError(f"Request failed after {MAX_RETRIES} retries")

    # =========================================================================
    # AUTHENTICATION
    # =========================================================================

    def test_connection(self) -> bool:
        """
        Test Confluence authentication.

        Returns:
            True if authentication successful, False otherwise
        """
        try:
            response = self._make_request(
                "GET",
                f"{self.base_url}/rest/api/user/current",
                timeout=10,
            )
            user_data = response.json()
            log(
                "ConfluenceClient: Connected",
                {"user": user_data.get("displayName", "Unknown")},
            )
            return True

        except Exception as e:
            log("ConfluenceClient: Connection failed", {"error": str(e)})
            return False

    # =========================================================================
    # PAGE OPERATIONS
    # =========================================================================

    def get_page(
        self, page_id: str, expand: str = "body.storage,version,space"
    ) -> Dict[str, Any]:
        """
        Get page by ID.

        Args:
            page_id: Confluence page ID
            expand: Fields to expand (default: body.storage,version,space)

        Returns:
            Page data dictionary
        """
        url = f"{self.base_url}/rest/api/content/{page_id}"
        response = self._make_request("GET", url, params={"expand": expand})
        return response.json()

    def validate_page_content(self, page_id: str) -> Dict[str, Any]:
        """
        Fetch a Confluence page and validate its storage format for rendering issues.

        Checks for:
        - Code blocks: missing CDATA, missing language parameter
        - PlantUML diagrams: missing markers, empty content
        - Unclosed HTML/XML tags
        - Empty macros
        - Malformed tables
        - Leftover placeholders
        - CDATA escaping issues

        Args:
            page_id: Confluence page ID

        Returns:
            Dictionary with validation results:
            {
                "valid": bool,
                "page_id": str,
                "title": str,
                "url": str,
                "issues": [{"type": str, "severity": str, "message": str, "snippet": str}, ...]
            }
        """
        page_data = self.get_page(page_id)
        title = page_data.get("title", "")
        space_key = page_data.get("space", {}).get("key", "")
        content = page_data.get("body", {}).get("storage", {}).get("value", "")
        url = f"{self.base_url}/wiki/spaces/{space_key}/pages/{page_id}"

        issues: List[Dict[str, str]] = []

        # 1. Validate code blocks
        code_macro_pattern = (
            r'<ac:structured-macro[^>]*ac:name="code"[^>]*>(.*?)</ac:structured-macro>'
        )
        for match in re.finditer(code_macro_pattern, content, re.DOTALL):
            macro_content = match.group(1)
            snippet = (
                match.group(0)[:100] + "..."
                if len(match.group(0)) > 100
                else match.group(0)
            )

            # Check for CDATA wrapper
            if "<![CDATA[" not in macro_content:
                issues.append(
                    {
                        "type": "code_block",
                        "severity": "error",
                        "message": "Code block missing CDATA wrapper - content may render as HTML",
                        "snippet": snippet,
                    }
                )

            # Check for language parameter
            if 'ac:name="language"' not in macro_content:
                issues.append(
                    {
                        "type": "code_block",
                        "severity": "warning",
                        "message": "Code block missing language parameter - no syntax highlighting",
                        "snippet": snippet,
                    }
                )

            # Check for empty code block
            if "<ac:plain-text-body>" in macro_content:
                body_match = re.search(
                    r"<ac:plain-text-body>(.*?)</ac:plain-text-body>",
                    macro_content,
                    re.DOTALL,
                )
                if body_match:
                    body_content = body_match.group(1).strip()
                    # Remove CDATA wrapper if present
                    body_content = re.sub(
                        r"<!\[CDATA\[(.*?)\]\]>", r"\1", body_content, flags=re.DOTALL
                    ).strip()
                    if not body_content:
                        issues.append(
                            {
                                "type": "code_block",
                                "severity": "warning",
                                "message": "Code block is empty",
                                "snippet": snippet,
                            }
                        )

        # 2. Validate PlantUML diagrams
        plantuml_pattern = r'<ac:structured-macro[^>]*ac:name="plantuml"[^>]*>(.*?)</ac:structured-macro>'
        for match in re.finditer(plantuml_pattern, content, re.DOTALL):
            macro_content = match.group(1)
            snippet = (
                match.group(0)[:100] + "..."
                if len(match.group(0)) > 100
                else match.group(0)
            )

            # Check for CDATA wrapper
            if "<![CDATA[" not in macro_content:
                issues.append(
                    {
                        "type": "diagram",
                        "severity": "error",
                        "message": "PlantUML diagram missing CDATA wrapper",
                        "snippet": snippet,
                    }
                )

            # Check for @startuml marker
            if "@startuml" not in macro_content:
                issues.append(
                    {
                        "type": "diagram",
                        "severity": "warning",
                        "message": "PlantUML diagram missing @startuml marker",
                        "snippet": snippet,
                    }
                )

            # Check for @enduml marker
            if "@enduml" not in macro_content:
                issues.append(
                    {
                        "type": "diagram",
                        "severity": "warning",
                        "message": "PlantUML diagram missing @enduml marker",
                        "snippet": snippet,
                    }
                )

            # Check for empty diagram
            body_match = re.search(
                r"<ac:plain-text-body>(.*?)</ac:plain-text-body>",
                macro_content,
                re.DOTALL,
            )
            if body_match:
                body_content = body_match.group(1).strip()
                body_content = re.sub(
                    r"<!\[CDATA\[(.*?)\]\]>", r"\1", body_content, flags=re.DOTALL
                ).strip()
                # Remove markers and check if empty
                body_content = (
                    body_content.replace("@startuml", "").replace("@enduml", "").strip()
                )
                if not body_content:
                    issues.append(
                        {
                            "type": "diagram",
                            "severity": "error",
                            "message": "PlantUML diagram has no content",
                            "snippet": snippet,
                        }
                    )

        # 3. Check for leftover placeholders (indicates conversion failure)
        placeholder_pattern = r"__[A-Z]+_PLACEHOLDER_\d+__"
        for match in re.finditer(placeholder_pattern, content):
            issues.append(
                {
                    "type": "placeholder",
                    "severity": "error",
                    "message": "Leftover placeholder found - content conversion failed",
                    "snippet": match.group(0),
                }
            )

        # 4. Check for CDATA escaping issues (]]> inside CDATA breaks XML)
        cdata_pattern = r"<!\[CDATA\[(.*?)\]\]>"
        for match in re.finditer(cdata_pattern, content, re.DOTALL):
            cdata_content = match.group(1)
            if "]]>" in cdata_content:
                issues.append(
                    {
                        "type": "cdata",
                        "severity": "error",
                        "message": "CDATA block contains unescaped ']]>' - will break XML parsing",
                        "snippet": (
                            match.group(0)[:100] + "..."
                            if len(match.group(0)) > 100
                            else match.group(0)
                        ),
                    }
                )

        # 5. Validate table structure
        table_pattern = (
            r'<table[^>]*class="[^"]*confluenceTable[^"]*"[^>]*>(.*?)</table>'
        )
        for match in re.finditer(table_pattern, content, re.DOTALL):
            table_content = match.group(1)
            snippet = (
                match.group(0)[:100] + "..."
                if len(match.group(0)) > 100
                else match.group(0)
            )

            # Count opening and closing tags
            tr_open = len(re.findall(r"<tr[^>]*>", table_content))
            tr_close = len(re.findall(r"</tr>", table_content))
            if tr_open != tr_close:
                issues.append(
                    {
                        "type": "table",
                        "severity": "error",
                        "message": f"Table has mismatched <tr> tags: {tr_open} opening, {tr_close} closing",
                        "snippet": snippet,
                    }
                )

            # Check for empty table
            if not re.search(r"<t[dh][^>]*>", table_content):
                issues.append(
                    {
                        "type": "table",
                        "severity": "warning",
                        "message": "Table has no cells",
                        "snippet": snippet,
                    }
                )

        # 6. Check for unclosed ac:structured-macro tags
        macro_open = len(re.findall(r"<ac:structured-macro[^>]*>", content))
        macro_close = len(re.findall(r"</ac:structured-macro>", content))
        if macro_open != macro_close:
            issues.append(
                {
                    "type": "macro",
                    "severity": "error",
                    "message": f"Mismatched macro tags: {macro_open} opening, {macro_close} closing",
                    "snippet": "",
                }
            )

        # 7. Check for basic HTML tag balance (common tags)
        for tag in ["p", "ul", "ol", "li", "strong", "em", "h1", "h2", "h3", "h4"]:
            open_count = len(re.findall(rf"<{tag}[^>]*>", content))
            close_count = len(re.findall(rf"</{tag}>", content))
            if open_count != close_count:
                issues.append(
                    {
                        "type": "formatting",
                        "severity": "warning",
                        "message": f"Mismatched <{tag}> tags: {open_count} opening, {close_count} closing",
                        "snippet": "",
                    }
                )

        return {
            "valid": len([i for i in issues if i["severity"] == "error"]) == 0,
            "page_id": page_id,
            "title": title,
            "url": url,
            "issues": issues,
        }

    def get_page_by_title(
        self,
        title: str,
        space_key: str | None = None,
    ) -> Dict[str, Any]:
        """
        Get page by title.

        Args:
            title: Page title
            space_key: Space key (uses default if not provided)

        Returns:
            Page data dictionary

        Raises:
            ValueError: If page not found
        """
        space = space_key or self.space_key
        if not space:
            raise ValueError("Space key required")

        url = f"{self.base_url}/rest/api/content"
        params = {
            "title": title,
            "spaceKey": space,
            "type": "page",
            "expand": "body.storage,version,space",
        }

        response = self._make_request("GET", url, params=params)
        results = response.json().get("results", [])

        if not results:
            raise ValueError(f"Page not found: {space}/{title}")

        return results[0]

    def find_page(self, title: str, space_key: str | None = None) -> str | None:
        """
        Find page ID by title.

        Args:
            title: Page title
            space_key: Space key (uses default if not provided)

        Returns:
            Page ID if found, None otherwise
        """
        try:
            page = self.get_page_by_title(title, space_key)
            return page.get("id")
        except ValueError:
            return None

    def docgen(
        self,
        title: str,
        filepath: str,
        parent_id: str | None = None,
        labels: List[str] | None = None,
        space_key: str | None = None,
    ) -> PageInfo:
        """
        Create a Confluence page from a markdown file.

        Reads the markdown file content and creates a page with automatic
        markdown-to-Confluence conversion.

        Args:
            title: Page title
            filepath: Path to markdown file (required)
            parent_id: Parent page ID (uses default if not provided)
            labels: Labels to apply
            space_key: Space key (uses default if not provided)

        Returns:
            PageInfo with created page details

        Raises:
            FileNotFoundError: If filepath does not exist
            ValueError: If filepath is not a markdown file
        """
        from pathlib import Path

        path = Path(filepath)

        if not path.exists():
            raise FileNotFoundError(f"Markdown file not found: {filepath}")

        if path.suffix.lower() not in (".md", ".markdown"):
            raise ValueError(
                f"File must be a markdown file (.md or .markdown): {filepath}"
            )

        content = path.read_text(encoding="utf-8")

        log(
            "ConfluenceClient: docgen",
            {"title": title, "filepath": filepath, "content_length": len(content)},
        )

        return self.create_page(
            title=title,
            content=content,
            parent_id=parent_id,
            labels=labels,
            space_key=space_key,
            convert_markdown=True,
        )

    def create_page(
        self,
        title: str,
        content: str,
        parent_id: str | None = None,
        labels: List[str] | None = None,
        space_key: str | None = None,
        convert_markdown: bool = True,
    ) -> PageInfo:
        """
        Create a new Confluence page.

        Args:
            title: Page title
            content: Page content (markdown or Confluence storage format)
            parent_id: Parent page ID (uses default if not provided)
            labels: Labels to apply
            space_key: Space key (uses default if not provided)
            convert_markdown: Whether to convert markdown to Confluence format

        Returns:
            PageInfo with created page details
        """
        space = space_key or self.space_key
        parent = parent_id or self.default_parent_id

        if not space:
            raise ValueError("Space key required")

        # Convert markdown if requested
        if convert_markdown:
            content = self.markdown_to_confluence(content)

        data: Dict[str, Any] = {
            "type": "page",
            "title": title,
            "space": {"key": space},
            "body": {"storage": {"value": content, "representation": "storage"}},
        }

        if parent:
            data["ancestors"] = [{"id": str(parent), "type": "page"}]

        url = f"{self.base_url}/rest/api/content"
        response = self._make_request("POST", url, json=data)
        page_data = response.json()

        page_id = page_data.get("id")

        # Add labels if provided
        if labels and page_id:
            self.add_labels(page_id, labels)

        log("ConfluenceClient: Page created", {"id": page_id, "title": title})

        return PageInfo(
            id=page_id,
            title=title,
            space_key=space,
            url=f"{self.base_url}/wiki/spaces/{space}/pages/{page_id}",
            version=1,
        )

    def update_page(
        self,
        page_id: str,
        title: str,
        content: str,
        convert_markdown: bool = True,
    ) -> PageInfo:
        """
        Update an existing Confluence page.

        Args:
            page_id: Page ID to update
            title: New page title
            content: New content (markdown or Confluence storage format)
            convert_markdown: Whether to convert markdown to Confluence format

        Returns:
            PageInfo with updated page details
        """
        # Get current version
        current = self.get_page(page_id, expand="version,space")
        current_version = current["version"]["number"]
        space_key = current["space"]["key"]

        # Convert markdown if requested
        if convert_markdown:
            content = self.markdown_to_confluence(content)

        data = {
            "version": {"number": current_version + 1},
            "title": title,
            "type": "page",
            "body": {"storage": {"value": content, "representation": "storage"}},
        }

        url = f"{self.base_url}/rest/api/content/{page_id}"
        response = self._make_request("PUT", url, json=data)
        page_data = response.json()

        log("ConfluenceClient: Page updated", {"id": page_id, "title": title})

        return PageInfo(
            id=page_id,
            title=title,
            space_key=space_key,
            url=f"{self.base_url}/wiki/spaces/{space_key}/pages/{page_id}",
            version=current_version + 1,
        )

    def delete_page(self, page_id: str) -> None:
        """
        Delete a Confluence page.

        Args:
            page_id: Page ID to delete
        """
        url = f"{self.base_url}/rest/api/content/{page_id}"
        self._make_request("DELETE", url)
        log("ConfluenceClient: Page deleted", {"id": page_id})

    def delete_recursive(self, page_id: str) -> None:
        """
        Delete a page and all its children recursively.

        Args:
            page_id: Page ID to delete (with children)
        """
        # Delete children first
        for child in self.get_children(page_id):
            self.delete_recursive(child.id)

        # Delete the page itself
        self.delete_page(page_id)

    def get_children(self, page_id: str) -> List[PageInfo]:
        """
        Get child pages of a parent page.

        Args:
            page_id: Parent page ID

        Returns:
            List of PageInfo for child pages
        """
        url = f"{self.base_url}/rest/api/content/{page_id}/child/page"
        response = self._make_request("GET", url, params={"expand": "space"})
        results = response.json().get("results", [])

        children = []
        for page in results:
            space_key = page.get("space", {}).get("key", "")
            children.append(
                PageInfo(
                    id=page["id"],
                    title=page["title"],
                    space_key=space_key,
                    url=f"{self.base_url}/wiki/spaces/{space_key}/pages/{page['id']}",
                )
            )

        return children

    # =========================================================================
    # LABELS
    # =========================================================================

    def add_labels(self, page_id: str, labels: List[str]) -> None:
        """
        Add labels to a page.

        Args:
            page_id: Page ID
            labels: List of label names
        """
        if not labels:
            return

        url = f"{self.base_url}/rest/api/content/{page_id}/label"

        for label in labels:
            data = [{"prefix": "global", "name": label}]
            try:
                self._make_request("POST", url, json=data)
            except Exception as e:
                log(
                    "ConfluenceClient: Failed to add label",
                    {
                        "page_id": page_id,
                        "label": label,
                        "error": str(e),
                    },
                )

    def get_labels(self, page_id: str) -> List[str]:
        """
        Get labels for a page.

        Args:
            page_id: Page ID

        Returns:
            List of label names
        """
        url = f"{self.base_url}/rest/api/content/{page_id}/label"
        response = self._make_request("GET", url)
        results = response.json().get("results", [])
        return [label["name"] for label in results]

    # =========================================================================
    # ATTACHMENTS
    # =========================================================================

    def get_attachments(self, page_id: str) -> List[Dict[str, Any]]:
        """
        Get attachments for a page.

        Args:
            page_id: Page ID

        Returns:
            List of attachment data dictionaries
        """
        url = f"{self.base_url}/rest/api/content/{page_id}/child/attachment"
        params = {"expand": "version", "limit": 100}

        attachments = []
        while url:
            response = self._make_request("GET", url, params=params)
            data = response.json()
            attachments.extend(data.get("results", []))

            if data.get("_links", {}).get("next"):
                url = self.base_url + data["_links"]["next"]
                params = {}
            else:
                break

        return attachments

    def download_attachment(self, attachment: Dict[str, Any]) -> bytes | None:
        """
        Download attachment binary data.

        Args:
            attachment: Attachment data dictionary

        Returns:
            Binary data or None if download fails
        """
        download_url = self.base_url + attachment["_links"]["download"]

        try:
            response = self._make_request("GET", download_url)
            return response.content
        except Exception as e:
            log(
                "ConfluenceClient: Failed to download attachment",
                {
                    "title": attachment.get("title"),
                    "error": str(e),
                },
            )
            return None

    def upload_attachment(
        self,
        page_id: str,
        filename: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> Dict[str, Any]:
        """
        Upload attachment to a page.

        Args:
            page_id: Page ID
            filename: Attachment filename
            data: Binary data
            content_type: MIME type

        Returns:
            Attachment data dictionary
        """
        url = f"{self.base_url}/rest/api/content/{page_id}/child/attachment"

        # Need special headers for file upload
        headers = {"X-Atlassian-Token": "nocheck"}
        files = {"file": (filename, data, content_type)}

        # Temporarily remove Content-Type header for multipart upload
        original_content_type = self.session.headers.pop("Content-Type", None)

        try:
            response = self._make_request("POST", url, files=files, headers=headers)
            return response.json()
        finally:
            if original_content_type:
                self.session.headers["Content-Type"] = original_content_type

    # =========================================================================
    # MACROS
    # =========================================================================

    def create_code_macro(self, language: str, code: str) -> str:
        """
        Create a Confluence code macro.

        Args:
            language: Programming language
            code: Code content

        Returns:
            Confluence storage format string
        """
        confluence_lang = LANGUAGE_MAP.get(language.lower(), language or "text")

        return (
            f'<ac:structured-macro ac:name="code" ac:schema-version="1">\n'
            f'<ac:parameter ac:name="language">{confluence_lang}</ac:parameter>\n'
            f'<ac:parameter ac:name="theme">RDark</ac:parameter>\n'
            f'<ac:parameter ac:name="linenumbers">true</ac:parameter>\n'
            f"<ac:plain-text-body><![CDATA[{code}]]></ac:plain-text-body>\n"
            f"</ac:structured-macro>"
        )

    def create_plantuml_macro(self, plantuml_content: str) -> str:
        """
        Create a PlantUML macro (DEPRECATED - use create_mermaid_macro instead).

        Args:
            plantuml_content: PlantUML diagram content

        Returns:
            Confluence storage format string
        """
        if not plantuml_content.strip().startswith("@startuml"):
            plantuml_content = "@startuml\n" + plantuml_content
        if not plantuml_content.strip().endswith("@enduml"):
            plantuml_content = plantuml_content + "\n@enduml"

        return (
            '<ac:structured-macro ac:name="plantuml" ac:schema-version="1">\n'
            '<ac:parameter ac:name="atlassian-macro-output-type">BLOCK</ac:parameter>\n'
            f"<ac:plain-text-body><![CDATA[{plantuml_content}]]></ac:plain-text-body>\n"
            "</ac:structured-macro>"
        )

    def create_mermaid_macro(self, mermaid_content: str) -> str:
        """
        Create a Confluence HTML macro with native Mermaid.js rendering.

        Uses the HTML macro to embed Mermaid.js from CDN, which renders
        diagrams client-side with perfect fidelity. No conversion needed.

        Supports ALL Mermaid diagram types:
        - flowchart/graph (TD, LR, etc.)
        - sequenceDiagram
        - classDiagram
        - stateDiagram
        - erDiagram
        - gantt
        - pie
        - timeline
        - mindmap
        - gitGraph
        - and more...

        Args:
            mermaid_content: Native Mermaid diagram syntax

        Returns:
            Confluence storage format HTML macro string
        """
        import hashlib

        # Generate unique ID based on content hash to avoid conflicts
        content_hash = hashlib.md5(mermaid_content.encode()).hexdigest()[:8]
        diagram_id = f"mermaid-{content_hash}"

        # Clean up the mermaid content - ensure proper formatting
        mermaid_clean = mermaid_content.strip()

        # Build HTML with Mermaid.js CDN
        # Using ESM module for modern browsers with fallback
        html_content = f"""<div id="{diagram_id}" class="mermaid" style="background: white; padding: 20px; border-radius: 8px;">
{mermaid_clean}
</div>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script>
(function() {{
    if (typeof mermaid !== 'undefined') {{
        mermaid.initialize({{
            startOnLoad: true,
            theme: 'default',
            securityLevel: 'loose',
            flowchart: {{ htmlLabels: true, curve: 'basis' }},
            sequence: {{ mirrorActors: false }}
        }});
        // Re-render in case page was already loaded
        if (document.readyState === 'complete') {{
            mermaid.init(undefined, '#{diagram_id}');
        }}
    }}
}})();
</script>"""

        # Wrap in Confluence HTML macro
        macro = (
            '<ac:structured-macro ac:name="html" ac:schema-version="1">\n'
            f"<ac:plain-text-body><![CDATA[{html_content}]]></ac:plain-text-body>\n"
            "</ac:structured-macro>"
        )

        return macro

    def create_toc_macro(self) -> str:
        """Create a Table of Contents macro."""
        return (
            '<ac:structured-macro ac:name="toc" ac:schema-version="1">\n'
            '<ac:parameter ac:name="printable">true</ac:parameter>\n'
            '<ac:parameter ac:name="style">disc</ac:parameter>\n'
            '<ac:parameter ac:name="maxLevel">3</ac:parameter>\n'
            '<ac:parameter ac:name="minLevel">1</ac:parameter>\n'
            "</ac:structured-macro>"
        )

    def create_children_macro(self, depth: int = 5) -> str:
        """
        Create a Children Display macro.

        Args:
            depth: Maximum depth of children to display

        Returns:
            Confluence storage format string
        """
        return (
            '<ac:structured-macro ac:name="children" ac:schema-version="2">\n'
            f'<ac:parameter ac:name="depth">{depth}</ac:parameter>\n'
            '<ac:parameter ac:name="all">true</ac:parameter>\n'
            '<ac:parameter ac:name="sort">title</ac:parameter>\n'
            "</ac:structured-macro>"
        )

    # =========================================================================
    # CONTENT CONVERSION
    # =========================================================================

    def mermaid_to_plantuml(self, mermaid_content: str) -> str:
        """
        Convert Mermaid diagram to PlantUML.

        Args:
            mermaid_content: Mermaid diagram content

        Returns:
            PlantUML diagram content
        """
        plantuml = "@startuml\n"

        if "timeline" in mermaid_content.lower():
            plantuml += self._convert_timeline(mermaid_content)
        elif mermaid_content.strip().startswith("graph"):
            plantuml += self._convert_flowchart(mermaid_content)
        elif mermaid_content.strip().startswith("sequenceDiagram"):
            plantuml += self._convert_sequence(mermaid_content)
        else:
            plantuml += "' Unknown diagram type converted from Mermaid\n"
            plantuml += 'note "Mermaid diagram" as N1\n'
            for line in mermaid_content.split("\n"):
                if line.strip():
                    plantuml += f"' {line}\n"

        plantuml += "@enduml"
        return plantuml

    def _convert_timeline(self, content: str) -> str:
        """Convert Mermaid timeline to PlantUML."""
        result = "' Timeline diagram converted from Mermaid\n"
        result += "skinparam backgroundColor white\n"
        result += "skinparam defaultFontName Arial\n\n"

        title = ""
        sections: List[Tuple[str, List[str]]] = []
        current_section = None
        section_items: List[str] = []

        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue

            if line.startswith("title "):
                title = line.replace("title", "").strip()
            elif line.startswith("section "):
                if current_section and section_items:
                    sections.append((current_section, section_items))
                    section_items = []
                current_section = line.replace("section", "").strip()
            elif ":" in line and current_section:
                section_items.append(line.strip())

        if current_section and section_items:
            sections.append((current_section, section_items))

        if title:
            result += f"title {title}\n\n"

        for i, (section_name, _) in enumerate(sections):
            result += f'rectangle "{section_name}" as section{i} #f0f0f0\n'

        for i in range(len(sections) - 1):
            result += f"section{i} -right-> section{i+1}\n"

        result += "\n"

        for i, (_, items) in enumerate(sections):
            for j, item in enumerate(items):
                item_id = f"item{i}_{j}"
                if ":" in item:
                    task, description = item.split(":", 1)
                    result += f'rectangle "{task.strip()}: {description.strip()}" as {item_id} #e5f2ff\n'
                else:
                    result += f'rectangle "{item}" as {item_id} #e5f2ff\n'
                result += f"{item_id} -up-> section{i}\n"

        return result

    def _convert_flowchart(self, content: str) -> str:
        """Convert Mermaid flowchart to PlantUML."""
        result = "' Flowchart diagram converted from Mermaid\n"
        result += "skinparam componentStyle rectangle\n\n"

        if "LR" in content:
            result += "left to right direction\n\n"
        else:
            result += "top to bottom direction\n\n"

        content_lines = content.split("\n")[1:]
        nodes: Dict[str, Dict[str, str]] = {}
        connections: List[Tuple[str, str, str | None]] = []

        for line in content_lines:
            line = line.strip()
            if not line or line.startswith("style ") or line.startswith("%%"):
                continue

            line = re.sub(r"<br\s*/?>", "\\n", line)

            node_patterns = [
                (r"(\w+)\[\(([^\)]+)\)\]", "database"),
                (r"(\w+)\(\(([^\)]+)\)\)", "circle"),
                (r"(\w+)\[([^\]]+)\]", "rectangle"),
                (r"(\w+)\(([^\)]+)\)", "rectangle"),
            ]

            for pattern, shape in node_patterns:
                for match in re.finditer(pattern, line):
                    node_id = match.group(1)
                    node_label = match.group(2)
                    if node_id not in nodes:
                        nodes[node_id] = {"label": node_label, "shape": shape}

            if "-->" in line:
                clean_line = re.sub(r"\[\([^\)]+\)\]", "", line)
                clean_line = re.sub(r"\(\([^\)]+\)\)", "", clean_line)
                clean_line = re.sub(r"\[[^\]]+\]", "", clean_line)
                clean_line = re.sub(r"\([^\)]+\)", "", clean_line)

                conn_match = re.match(
                    r"(\w+)\s*-->\s*(\w+)(?:\s*:\s*(.+))?", clean_line.strip()
                )
                if conn_match:
                    connections.append(
                        (
                            conn_match.group(1),
                            conn_match.group(2),
                            conn_match.group(3),
                        )
                    )

        for node_id, info in nodes.items():
            label = info["label"].replace('"', "'").replace("\n", "\\n")
            if info["shape"] == "database":
                result += f'database "{label}" as {node_id}\n'
            else:
                result += f'rectangle "{label}" as {node_id}\n'

        result += "\n"

        for from_node, to_node, label in connections:
            if label:
                result += f"{from_node} --> {to_node} : {label}\n"
            else:
                result += f"{from_node} --> {to_node}\n"

        return result

    def _convert_sequence(self, content: str) -> str:
        """Convert Mermaid sequence diagram to PlantUML."""
        result = "' Sequence diagram converted from Mermaid\n"
        result += "skinparam sequenceMessageAlign center\n\n"

        lines = content.split("\n")[1:]

        for line in lines:
            line = line.strip()
            if not line or line.startswith("%%"):
                continue

            line = re.sub(r"<br\s*/?>", "\\n", line)

            if line.startswith("participant "):
                part_match = re.match(r"participant\s+(\w+)\s+as\s+(.+)", line)
                if part_match:
                    alias = part_match.group(1)
                    name = part_match.group(2).strip()
                    result += f'participant "{name}" as {alias}\n'
                else:
                    simple_match = re.match(r"participant\s+(\w+)", line)
                    if simple_match:
                        result += f"participant {simple_match.group(1)}\n"

            elif line.startswith(("alt ", "else ", "end", "loop ", "opt ", "note ")):
                result += line + "\n"

            elif "->>" in line or "-->>" in line or "->" in line or "-->" in line:
                arrow_match = re.match(
                    r"(\w+)\s*(--?>>?[\+\-]?)\s*(\w+)\s*:\s*(.+)", line
                )
                if arrow_match:
                    source = arrow_match.group(1)
                    arrow = arrow_match.group(2)
                    target = arrow_match.group(3)
                    message = arrow_match.group(4).strip()

                    plantuml_arrow = "-->" if "--" in arrow else "->"
                    result += f"{source} {plantuml_arrow} {target} : {message}\n"
                else:
                    simple_match = re.match(r"(\w+)\s*(--?>>?[\+\-]?)\s*(\w+)", line)
                    if simple_match:
                        source = simple_match.group(1)
                        arrow = simple_match.group(2)
                        target = simple_match.group(3)
                        plantuml_arrow = "-->" if "--" in arrow else "->"
                        result += f"{source} {plantuml_arrow} {target}\n"

        return result

    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        text = text.replace("&", "&amp;")
        text = text.replace("<", "&lt;")
        text = text.replace(">", "&gt;")
        text = text.replace('"', "&quot;")
        return text

    def _convert_table(self, table_lines: List[str]) -> str:
        """Convert markdown table to Confluence HTML table."""
        if len(table_lines) < 2:
            return "\n".join(table_lines)

        html = '<table class="confluenceTable">\n<tbody>\n'

        for i, line in enumerate(table_lines):
            if re.match(r"^\|[\s\-:|]+\|$", line.strip()):
                continue

            cells = [c.strip() for c in line.strip().strip("|").split("|")]

            if i == 0:
                html += "<tr>\n"
                for cell in cells:
                    escaped = self._escape_html(cell)
                    html += f'<th class="confluenceTh">{escaped}</th>\n'
                html += "</tr>\n"
            else:
                html += "<tr>\n"
                for cell in cells:
                    escaped = self._escape_html(cell)
                    html += f'<td class="confluenceTd">{escaped}</td>\n'
                html += "</tr>\n"

        html += "</tbody>\n</table>"
        return html

    def markdown_to_confluence(self, markdown_content: str) -> str:
        """
        Convert markdown content to Confluence storage format.

        Handles:
        - Headers (h1-h4)
        - Bold, italic
        - Links
        - Lists (ordered and unordered)
        - Code blocks with syntax highlighting
        - Mermaid diagrams (converted to PlantUML)
        - Tables
        - Inline code

        Args:
            markdown_content: Markdown content

        Returns:
            Confluence storage format HTML
        """
        html_content = markdown_content

        # Step 1: Extract mermaid blocks and render with native Mermaid.js (via HTML macro)
        # NO PlantUML conversion - keeps native Mermaid syntax for perfect rendering
        mermaid_pattern = r"```\s*mermaid\s*(.*?)\s*```"
        mermaid_placeholders: Dict[str, str] = {}

        for i, match in enumerate(
            re.finditer(mermaid_pattern, html_content, re.DOTALL)
        ):
            mermaid = match.group(1).strip()
            placeholder = f"__MERMAID_PLACEHOLDER_{i}__"
            # Use native Mermaid rendering via HTML macro (no conversion needed)
            mermaid_placeholders[placeholder] = self.create_mermaid_macro(mermaid)
            html_content = html_content.replace(match.group(0), placeholder)

        # Step 2: Extract and convert code blocks
        # Pattern allows optional whitespace before closing ``` (handles indented markdown)
        code_pattern = r"```(\w*)[ \t]*\n(.*?)\n[ \t]*```"
        code_placeholders: Dict[str, str] = {}

        for i, match in enumerate(re.finditer(code_pattern, html_content, re.DOTALL)):
            lang = match.group(1) or "text"
            code = match.group(2)
            if lang.lower() != "mermaid":
                placeholder = f"__CODE_PLACEHOLDER_{i}__"
                code_placeholders[placeholder] = self.create_code_macro(lang, code)
                html_content = html_content.replace(match.group(0), placeholder)

        # Step 3: Extract and convert tables
        table_placeholders: Dict[str, str] = {}
        table_pattern = r"(\|.+\|\n)+"
        table_idx = 0

        for match in re.finditer(table_pattern, html_content):
            table_text = match.group(0).strip()
            table_lines = table_text.split("\n")
            if len(table_lines) >= 2 and any(
                re.match(r"^\|[\s\-:|]+\|$", line.strip()) for line in table_lines
            ):
                placeholder = f"__TABLE_PLACEHOLDER_{table_idx}__"
                table_placeholders[placeholder] = self._convert_table(table_lines)
                html_content = html_content.replace(match.group(0), placeholder + "\n")
                table_idx += 1

        # Step 4: Extract inline code
        inline_code_placeholders: Dict[str, str] = {}
        inline_pattern = r"`([^`]+)`"

        for i, match in enumerate(re.finditer(inline_pattern, html_content)):
            code_text = match.group(1)
            placeholder = f"__INLINE_CODE_{i}__"
            escaped_code = self._escape_html(code_text)
            inline_code_placeholders[placeholder] = f"<code>{escaped_code}</code>"
            html_content = html_content.replace(match.group(0), placeholder, 1)

        # Step 5: Escape HTML in remaining text
        lines = html_content.split("\n")
        escaped_lines = []
        for line in lines:
            if line.strip().startswith("__") and line.strip().endswith("__"):
                escaped_lines.append(line)
            elif line.strip().startswith("<"):
                escaped_lines.append(line)
            else:
                parts = re.split(r"(__\w+_\d+__)", line)
                escaped_parts = []
                for part in parts:
                    if re.match(r"__\w+_\d+__", part):
                        escaped_parts.append(part)
                    else:
                        escaped_parts.append(self._escape_html(part))
                escaped_lines.append("".join(escaped_parts))

        html_content = "\n".join(escaped_lines)

        # Step 6: Convert markdown syntax
        html_content = re.sub(
            r"^#### (.+)$", r"<h4>\1</h4>", html_content, flags=re.MULTILINE
        )
        html_content = re.sub(
            r"^### (.+)$", r"<h3>\1</h3>", html_content, flags=re.MULTILINE
        )
        html_content = re.sub(
            r"^## (.+)$", r"<h2>\1</h2>", html_content, flags=re.MULTILINE
        )
        html_content = re.sub(
            r"^# (.+)$", r"<h1>\1</h1>", html_content, flags=re.MULTILINE
        )

        html_content = re.sub(
            r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", html_content
        )
        html_content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html_content)
        html_content = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html_content)

        def replace_link(match):
            text = match.group(1)
            url = match.group(2).replace("&amp;", "&")
            return f'<a href="{url}">{text}</a>'

        html_content = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace_link, html_content)

        html_content = re.sub(
            r"^- (.+)$", r"<li>\1</li>", html_content, flags=re.MULTILINE
        )
        html_content = re.sub(
            r"^\d+\. (.+)$", r"<li>\1</li>", html_content, flags=re.MULTILINE
        )
        html_content = re.sub(
            r"^&gt; (.+)$",
            r"<blockquote>\1</blockquote>",
            html_content,
            flags=re.MULTILINE,
        )
        html_content = re.sub(r"^---+$", r"<hr/>", html_content, flags=re.MULTILINE)

        # Wrap lists
        lines = html_content.split("\n")
        result = []
        in_list = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("<li>"):
                if not in_list:
                    result.append("<ul>")
                    in_list = True
                result.append(line)
            else:
                if in_list:
                    result.append("</ul>")
                    in_list = False
                result.append(line)

        if in_list:
            result.append("</ul>")

        html_content = "\n".join(result)

        # Wrap paragraphs
        lines = html_content.split("\n")
        result = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                result.append(line)
            elif stripped.startswith("<") or stripped.startswith("__"):
                result.append(line)
            elif stripped in ("</ul>", "</ol>", "<ul>", "<ol>"):
                result.append(line)
            else:
                result.append(f"<p>{stripped}</p>")

        html_content = "\n".join(result)

        # Step 7: Replace placeholders
        for placeholder, macro in mermaid_placeholders.items():
            html_content = html_content.replace(placeholder, macro)
            html_content = html_content.replace(f"<p>{placeholder}</p>", macro)

        for placeholder, macro in code_placeholders.items():
            html_content = html_content.replace(placeholder, macro)
            html_content = html_content.replace(f"<p>{placeholder}</p>", macro)

        for placeholder, table_html in table_placeholders.items():
            html_content = html_content.replace(placeholder, table_html)
            html_content = html_content.replace(f"<p>{placeholder}</p>", table_html)

        for placeholder, code_html in inline_code_placeholders.items():
            html_content = html_content.replace(placeholder, code_html)

        return html_content

    # =========================================================================
    # UTILITIES
    # =========================================================================

    @staticmethod
    def parse_url(url: str) -> Tuple[str, str | None, str | None]:
        """
        Parse Confluence URL to extract base URL, space key, and page ID.

        Supports:
        - /display/SPACE/Page+Title
        - /pages/viewpage.action?pageId=123456
        - /wiki/spaces/SPACE/pages/123456/Page+Title

        Args:
            url: Confluence page URL

        Returns:
            Tuple of (base_url, space_key, page_id)

        Raises:
            ValueError: If URL format not recognized
        """
        from urllib.parse import urlparse

        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"

        # Pattern 1: /display/SPACE/Page+Title
        display_match = re.search(r"/display/([^/]+)/(.+)", parsed.path)
        if display_match:
            return base, display_match.group(1), None

        # Pattern 2: /pages/viewpage.action?pageId=123456
        if "pageId=" in url:
            page_id_match = re.search(r"pageId=(\d+)", url)
            if page_id_match:
                return base, None, page_id_match.group(1)

        # Pattern 3: /wiki/spaces/SPACE/pages/123456/Page+Title
        cloud_match = re.search(r"/wiki/spaces/([^/]+)/pages/(\d+)", parsed.path)
        if cloud_match:
            return base, cloud_match.group(1), cloud_match.group(2)

        raise ValueError(f"Could not parse Confluence URL: {url}")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def get_confluence_client() -> ConfluenceClient:
    """Convenience function to get Confluence client."""
    return ConfluenceClient.get_client()
