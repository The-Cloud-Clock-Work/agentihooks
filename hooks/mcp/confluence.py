"""Confluence MCP tools."""

import json

from hooks.common import log


def register(mcp):
    @mcp.tool()
    def confluence_get_page(page_id: str) -> str:
        """Get a Confluence page by ID.

        Args:
            page_id: Confluence page ID

        Returns:
            JSON with page id, title, space_key, version, and url
        """
        try:
            from hooks.integrations.confluence import ConfluenceClient

            client = ConfluenceClient.get_client()
            page = client.get_page(page_id)

            return json.dumps(
                {
                    "success": True,
                    "id": page.get("id"),
                    "title": page.get("title"),
                    "space_key": page.get("space", {}).get("key"),
                    "version": page.get("version", {}).get("number"),
                    "url": f"{client.base_url}/wiki/spaces/{page.get('space', {}).get('key')}/pages/{page.get('id')}",
                }
            )

        except Exception as e:
            log("MCP confluence_get_page failed", {"page_id": page_id, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def confluence_find_page(title: str, space_key: str = "") -> str:
        """Find a Confluence page ID by title.

        Args:
            title: Page title to search for
            space_key: Space key (uses default from env if not provided)

        Returns:
            JSON with page id, title, and url if found, or found=false
        """
        try:
            from hooks.integrations.confluence import ConfluenceClient

            client = ConfluenceClient.get_client()
            space = space_key or client.space_key

            page_id = client.find_page(title, space)

            if page_id:
                return json.dumps(
                    {
                        "success": True,
                        "found": True,
                        "id": page_id,
                        "title": title,
                        "space_key": space,
                        "url": f"{client.base_url}/wiki/spaces/{space}/pages/{page_id}",
                    }
                )
            else:
                return json.dumps(
                    {
                        "success": True,
                        "found": False,
                        "title": title,
                        "space_key": space,
                    }
                )

        except Exception as e:
            log("MCP confluence_find_page failed", {"title": title, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def confluence_create_page(
        title: str,
        content: str,
        parent_id: str = "",
        space_key: str = "",
        labels: str = "",
        convert_markdown: bool = True,
    ) -> str:
        """Create a new Confluence page.

        Args:
            title: Page title
            content: Page content (markdown or Confluence storage format)
            parent_id: Parent page ID (uses default from env if not provided)
            space_key: Space key (uses default from env if not provided)
            labels: Comma-separated labels to apply or list
            convert_markdown: Whether to convert markdown to Confluence format (default: True)

        Returns:
            JSON with page id, title, space_key, url, and version
        """
        try:
            from hooks.integrations.confluence import ConfluenceClient

            client = ConfluenceClient.get_client()
            if isinstance(labels, list):
                label_list = [l.strip() for l in labels if l.strip()]
            elif labels:
                label_list = [l.strip() for l in labels.split(",") if l.strip()]
            else:
                label_list = None

            page_info = client.create_page(
                title=title,
                content=content,
                parent_id=parent_id if parent_id else None,
                labels=label_list,
                space_key=space_key if space_key else None,
                convert_markdown=convert_markdown,
            )

            return json.dumps(
                {
                    "success": True,
                    "id": page_info.id,
                    "title": page_info.title,
                    "space_key": page_info.space_key,
                    "url": page_info.url,
                    "version": page_info.version,
                }
            )

        except Exception as e:
            log("MCP confluence_create_page failed", {"title": title, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def confluence_update_page(
        page_id: str,
        title: str,
        content: str,
        convert_markdown: bool = True,
    ) -> str:
        """Update an existing Confluence page.

        Args:
            page_id: Page ID to update
            title: New page title
            content: New content (markdown or Confluence storage format)
            convert_markdown: Whether to convert markdown to Confluence format (default: True)

        Returns:
            JSON with page id, title, space_key, url, and new version
        """
        try:
            from hooks.integrations.confluence import ConfluenceClient

            client = ConfluenceClient.get_client()
            page_info = client.update_page(
                page_id=page_id,
                title=title,
                content=content,
                convert_markdown=convert_markdown,
            )

            return json.dumps(
                {
                    "success": True,
                    "id": page_info.id,
                    "title": page_info.title,
                    "space_key": page_info.space_key,
                    "url": page_info.url,
                    "version": page_info.version,
                }
            )

        except Exception as e:
            log("MCP confluence_update_page failed", {"page_id": page_id, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def confluence_delete_page(page_id: str, recursive: bool = False) -> str:
        """Delete a Confluence page.

        Args:
            page_id: Page ID to delete
            recursive: If True, delete all child pages first (default: False)

        Returns:
            JSON with success status
        """
        try:
            from hooks.integrations.confluence import ConfluenceClient

            client = ConfluenceClient.get_client()

            if recursive:
                client.delete_recursive(page_id)
            else:
                client.delete_page(page_id)

            return json.dumps(
                {
                    "success": True,
                    "page_id": page_id,
                    "recursive": recursive,
                }
            )

        except Exception as e:
            log("MCP confluence_delete_page failed", {"page_id": page_id, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def confluence_get_child_pages(parent_id: str) -> str:
        """Get child pages of a parent page.

        Args:
            parent_id: Parent page ID

        Returns:
            JSON with list of child pages (id, title, url)
        """
        try:
            from hooks.integrations.confluence import ConfluenceClient

            client = ConfluenceClient.get_client()
            children = client.get_children(parent_id)

            return json.dumps(
                {
                    "success": True,
                    "parent_id": parent_id,
                    "count": len(children),
                    "children": [
                        {
                            "id": child.id,
                            "title": child.title,
                            "space_key": child.space_key,
                            "url": child.url,
                        }
                        for child in children
                    ],
                }
            )

        except Exception as e:
            log("MCP confluence_get_child_pages failed", {"parent_id": parent_id, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def confluence_docgen(
        title: str,
        filepath: str,
        parent_id: str = "",
        space_key: str = "",
        labels: str = "",
    ) -> str:
        """Create a Confluence page from a markdown file.

        Reads the markdown file and creates a Confluence page with automatic
        markdown-to-Confluence format conversion.

        Args:
            title: Page title
            filepath: Path to markdown file (required, must be .md or .markdown)
            parent_id: Parent page ID (uses default from env if not provided)
            space_key: Space key (uses default from env if not provided)
            labels: Comma-separated labels to apply or list

        Returns:
            JSON with page id, title, space_key, url, and version
        """
        try:
            from hooks.integrations.confluence import ConfluenceClient

            client = ConfluenceClient.get_client()

            if isinstance(labels, list):
                label_list = [l.strip() for l in labels if l.strip()]
            elif labels:
                label_list = [l.strip() for l in labels.split(",") if l.strip()]
            else:
                label_list = None

            page_info = client.docgen(
                title=title,
                filepath=filepath,
                parent_id=parent_id if parent_id else None,
                labels=label_list,
                space_key=space_key if space_key else None,
            )

            return json.dumps(
                {
                    "success": True,
                    "id": page_info.id,
                    "title": page_info.title,
                    "space_key": page_info.space_key,
                    "url": page_info.url,
                    "version": page_info.version,
                }
            )

        except FileNotFoundError as e:
            log("MCP confluence_docgen file not found", {"filepath": filepath, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

        except ValueError as e:
            log("MCP confluence_docgen validation failed", {"filepath": filepath, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

        except Exception as e:
            log("MCP confluence_docgen failed", {"title": title, "filepath": filepath, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def confluence_validate_page(page_id: str) -> str:
        """Validate a Confluence page for rendering issues.

        Fetches the page and checks for:
        - Code blocks: missing CDATA, missing language parameter, empty blocks
        - PlantUML diagrams: missing markers, empty content
        - Unclosed HTML/XML tags
        - Empty macros
        - Malformed tables
        - Leftover placeholders
        - CDATA escaping issues

        Args:
            page_id: Confluence page ID

        Returns:
            JSON with validation results: valid (bool), issues (list), page details
        """
        try:
            from hooks.integrations.confluence import ConfluenceClient

            client = ConfluenceClient.get_client()
            result = client.validate_page_content(page_id)

            return json.dumps(
                {
                    "success": True,
                    "valid": result["valid"],
                    "page_id": result["page_id"],
                    "title": result["title"],
                    "url": result["url"],
                    "issues": result["issues"],
                }
            )

        except Exception as e:
            log("MCP confluence_validate_page failed", {"page_id": page_id, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def confluence_test_connection() -> str:
        """Test Confluence authentication and connection.

        Returns:
            JSON with connection status and user info
        """
        try:
            from hooks.integrations.confluence import ConfluenceClient

            client = ConfluenceClient.get_client()
            connected = client.test_connection()

            return json.dumps(
                {
                    "success": True,
                    "connected": connected,
                    "base_url": client.base_url,
                    "space_key": client.space_key,
                    "default_parent_id": client.default_parent_id,
                }
            )

        except Exception as e:
            log("MCP confluence_test_connection failed", {"error": str(e)})
            return json.dumps({"success": False, "connected": False, "error": str(e)})
