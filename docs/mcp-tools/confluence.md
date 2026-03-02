---
title: Confluence
nav_order: 3
---

# Confluence Tools
{: .no_toc }

The Confluence category provides full CRUD operations on Confluence pages, markdown-to-storage-format conversion, page validation, and documentation generation from local files.

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Tools

| Tool | Description |
|------|-------------|
| `confluence_get_page()` | Fetch a page by ID |
| `confluence_find_page()` | Find a page by title (with optional space filter) |
| `confluence_create_page()` | Create a new page |
| `confluence_update_page()` | Update an existing page |
| `confluence_delete_page()` | Delete a page (optionally recursive) |
| `confluence_get_child_pages()` | List child pages of a parent |
| `confluence_docgen()` | Create a page from a local markdown file |
| `confluence_validate_page()` | Check a page for rendering issues |
| `confluence_test_connection()` | Verify auth and connectivity |

---

## Tool reference

### `confluence_get_page`

```python
confluence_get_page(page_id: str) -> str
```

**Returns:** JSON with `id`, `title`, `space_key`, `version`, `url`

---

### `confluence_find_page`

```python
confluence_find_page(title: str, space_key: str = "") -> str
```

Searches by exact title. Optionally scoped to a space.

**Returns:** JSON with `found` (bool), `id`, `title`, `space_key`, `url`

---

### `confluence_create_page`

```python
confluence_create_page(
    title: str,
    content: str,
    parent_id: str = "",
    space_key: str = "",
    labels: str = "",
    convert_markdown: bool = True
) -> str
```

Creates a new page. When `convert_markdown=True` (default), the `content` is treated as markdown and auto-converted to Confluence storage format. `labels` is a comma-separated string.

**Returns:** JSON with `id`, `title`, `space_key`, `url`, `version`

---

### `confluence_update_page`

```python
confluence_update_page(
    page_id: str,
    title: str,
    content: str,
    convert_markdown: bool = True
) -> str
```

Fetches the current version, increments it, and publishes the update.

**Returns:** JSON with `id`, `title`, `space_key`, `url`, `version`

---

### `confluence_delete_page`

```python
confluence_delete_page(page_id: str, recursive: bool = False) -> str
```

When `recursive=True`, deletes all child pages before the parent.

**Returns:** JSON with `page_id`, `recursive`

---

### `confluence_get_child_pages`

```python
confluence_get_child_pages(parent_id: str) -> str
```

**Returns:** JSON with `parent_id`, `count`, `children` (list of `id`, `title`, `space_key`, `url`)

---

### `confluence_docgen`

```python
confluence_docgen(
    title: str,
    filepath: str,
    parent_id: str = "",
    space_key: str = "",
    labels: str = ""
) -> str
```

Reads a local markdown file, converts it to Confluence storage format, and creates (or updates) the page.

**Returns:** JSON with `id`, `title`, `space_key`, `url`, `version`

---

### `confluence_validate_page`

```python
confluence_validate_page(page_id: str) -> str
```

Fetches the page and checks for common rendering issues: malformed code blocks, PlantUML syntax errors, CDATA sections, and encoding problems.

**Returns:** JSON with `valid` (bool), `page_id`, `title`, `url`, `issues` (list)

---

### `confluence_test_connection`

```python
confluence_test_connection() -> str
```

Pings the Confluence API to verify credentials and connectivity.

**Returns:** JSON with `connected` (bool), `base_url`, `space_key`, `default_parent_id`

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CONFLUENCE_SERVER_URL` | Yes | — | Confluence base URL (e.g., `https://myorg.atlassian.net/wiki`) |
| `CONFLUENCE_TOKEN` | Yes | — | Confluence API token |
| `CONFLUENCE_SPACE_KEY` | No | — | Default space key (used when `space_key` is omitted in calls) |
| `PARENT_PAGE_ID` | No | — | Default parent page ID for new pages |
