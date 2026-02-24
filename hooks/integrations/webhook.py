#!/usr/bin/env python3
"""HTTP webhook integration for sending payloads to external endpoints from hooks.

Sends JSON payloads to HTTP endpoints with optional header-based authentication.
This enables integration with external services (Teams, Slack, custom webhooks, etc.)
without embedding platform-specific logic in the agent.

Environment Variables:
    WEBHOOK_URL: HTTP endpoint URL (required for sending)
    WEBHOOK_AUTH_HEADER: Auth header name (default: X-Auth-Token)
    WEBHOOK_AUTH_TOKEN: Auth token value (optional, adds header if set)
    WEBHOOK_TIMEOUT: Request timeout in seconds (default: 30)
    IS_EVALUATION: Skip sending in evaluation mode (default: false)

Usage:
    # Python import
    from hooks.integrations.http import send

    # Simple send
    result = send({"event": "completion", "status": "success"})

    # With state enrichment
    result = send(
        {"session_id": "uuid-123", "transcript_path": "/path"},
        enrich_from_state=True
    )

    # CLI - Check configuration
    /app/hooks/integrations/http.py check [--json]

    # CLI - As hook (reads from stdin)
    /app/hooks/integrations/http.py hook < stop_event.json
    /app/hooks/integrations/http.py hook --demo

    # CLI - Direct send
    /app/hooks/integrations/http.py send '{"key": "value"}'
"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

# Add parent directories to path for direct script execution
_script_dir = Path(__file__).resolve().parent
_app_dir = _script_dir.parent.parent  # /app
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))

try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

from hooks.common import log
from hooks.integrations.base import IntegrationBase, IntegrationRegistry

# =============================================================================
# INTEGRATION DEFINITION
# =============================================================================


@IntegrationRegistry.register
class HTTPIntegration(IntegrationBase):
    """HTTP webhook integration configuration checker."""

    INTEGRATION_NAME = "http"
    REQUIRED_ENV_VARS = {
        "WEBHOOK_URL": "HTTP endpoint URL for sending payloads",
    }
    OPTIONAL_ENV_VARS = {
        "WEBHOOK_AUTH_HEADER": "Auth header name (default: X-Auth-Token)",
        "WEBHOOK_AUTH_TOKEN": "Auth token value (adds header if set)",
        "WEBHOOK_TIMEOUT": "Request timeout in seconds (default: 30)",
        "IS_EVALUATION": "Skip sending in evaluation mode (default: false)",
    }


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_STATE_FILE = Path.home() / "conversation_map.json"


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class HTTPResult:
    """Result of HTTP send operation."""

    success: bool
    status_code: Optional[int] = None
    response_body: Optional[str] = None
    webhook_url: Optional[str] = None
    error: Optional[str] = None


# =============================================================================
# STATE MANAGEMENT
# =============================================================================


def load_state(session_id: str, state_file: Optional[Path] = None) -> Dict[str, Any]:
    """Load state data for a session from conversation_map.json.

    Args:
        session_id: Session UUID to look up
        state_file: Custom state file path (default: ~/conversation_map.json)

    Returns:
        Dict with state data, or empty dict if not found
    """
    state_path = state_file or DEFAULT_STATE_FILE

    try:
        if not state_path.exists():
            return {}

        mappings = json.loads(state_path.read_text())
        state = mappings.get(session_id, {})

        # Handle legacy format (string only) - convert to dict
        if isinstance(state, str):
            return {"conversation_id": state, "wait": False}

        return state if isinstance(state, dict) else {}

    except Exception as e:
        log("Failed to load state", {"session_id": session_id, "error": str(e)})
        return {}


# =============================================================================
# HTTP CLIENT
# =============================================================================


class HTTPClient:
    """HTTP webhook client using httpx."""

    _instance: Optional["HTTPClient"] = None

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        auth_header: Optional[str] = None,
        auth_token: Optional[str] = None,
        timeout: Optional[int] = None,
        skip_evaluation: bool = True,
        state_file: Optional[Path] = None,
    ):
        """Initialize HTTP client.

        Args:
            webhook_url: HTTP endpoint URL (default: from env WEBHOOK_URL)
            auth_header: Auth header name (default: from env or X-Auth-Token)
            auth_token: Auth token value (default: from env WEBHOOK_AUTH_TOKEN)
            timeout: Request timeout in seconds (default: from env or 30)
            skip_evaluation: Skip sending when IS_EVALUATION=true (default: True)
            state_file: Custom state file path (default: ~/conversation_map.json)
        """
        self._webhook_url = webhook_url or os.getenv("WEBHOOK_URL", "")
        self._auth_header = auth_header or os.getenv("WEBHOOK_AUTH_HEADER", "X-Auth-Token")
        self._auth_token = auth_token or os.getenv("WEBHOOK_AUTH_TOKEN", "")
        self._timeout = timeout or int(os.getenv("WEBHOOK_TIMEOUT", "30"))
        self._skip_evaluation = skip_evaluation
        self._state_file = state_file or DEFAULT_STATE_FILE
        self._http_client = None

        # Check if we should skip (evaluation mode)
        self._is_evaluation = os.getenv("IS_EVALUATION", "false").lower() == "true"

    @classmethod
    def get_client(
        cls,
        webhook_url: Optional[str] = None,
        auth_header: Optional[str] = None,
        auth_token: Optional[str] = None,
        timeout: Optional[int] = None,
        skip_evaluation: bool = True,
        state_file: Optional[Path] = None,
    ) -> "HTTPClient":
        """Get singleton instance."""
        if cls._instance is None or webhook_url or auth_token or state_file:
            cls._instance = cls(
                webhook_url=webhook_url,
                auth_header=auth_header,
                auth_token=auth_token,
                timeout=timeout,
                skip_evaluation=skip_evaluation,
                state_file=state_file,
            )
        return cls._instance

    @classmethod
    def clear_cache(cls) -> None:
        """Clear cached instance (for testing)."""
        cls._instance = None

    @property
    def client(self) -> "httpx.Client":
        """Lazy-load httpx client."""
        if self._http_client is None:
            if not HTTPX_AVAILABLE:
                raise ImportError("httpx is required for HTTP integration")
            self._http_client = httpx.Client(
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=float(self._timeout),
                    write=30.0,
                    pool=10.0,
                )
            )
        return self._http_client

    def should_skip(self) -> bool:
        """Check if sending should be skipped."""
        # Skip if no webhook URL configured
        if not self._webhook_url:
            log(
                "HTTP send skipped: WEBHOOK_URL not configured",
                {"integration": "http", "reason": "missing_config", "var": "WEBHOOK_URL"},
            )
            return True

        # Skip if evaluation mode
        if self._skip_evaluation and self._is_evaluation:
            log(
                "HTTP send skipped: IS_EVALUATION=true",
                {"integration": "http", "reason": "evaluation_mode"},
            )
            return True

        return False

    def send(
        self,
        payload: Dict[str, Any],
        method: str = "POST",
        enrich_from_state: bool = False,
    ) -> HTTPResult:
        """Send a payload to the webhook URL.

        Args:
            payload: Message data to send (JSON serializable)
            method: HTTP method (default: POST)
            enrich_from_state: If True and payload has 'session_id',
                              merges data from conversation_map.json

        Returns:
            HTTPResult with success status and response info
        """
        # Check if we should skip sending
        if self.should_skip():
            return HTTPResult(
                success=True,
                webhook_url=self._webhook_url or "not-configured",
            )

        try:
            # Enrich with state if requested
            enriched_payload = payload.copy()

            if enrich_from_state and "session_id" in payload:
                session_id = payload["session_id"]
                state = load_state(session_id, self._state_file)

                # Check if wait=true (skip HTTP for synchronous responses)
                if state.get("wait", False):
                    log(
                        "Skipping HTTP send",
                        {
                            "reason": "wait=true (synchronous response)",
                            "session_id": session_id,
                        },
                    )
                    return HTTPResult(
                        success=True,
                        webhook_url=self._webhook_url,
                    )

                # Merge state into payload (payload overrides state)
                enriched_payload = {**state, **payload}

                log(
                    "Enriched payload with state",
                    {
                        "session_id": session_id,
                        "state_fields": list(state.keys()),
                    },
                )

            # Build headers
            headers = {"Content-Type": "application/json"}
            if self._auth_token:
                headers[self._auth_header] = self._auth_token

            # Send request
            log(
                "Sending HTTP request",
                {
                    "webhook_url": self._webhook_url,
                    "method": method,
                    "payload_size": len(json.dumps(enriched_payload)),
                    "has_auth": bool(self._auth_token),
                },
            )

            response = self.client.request(
                method=method.upper(),
                url=self._webhook_url,
                json=enriched_payload,
                headers=headers,
            )

            # Check response
            success = 200 <= response.status_code < 300

            log(
                "HTTP send completed",
                {
                    "status_code": response.status_code,
                    "success": success,
                    "webhook_url": self._webhook_url,
                },
            )

            return HTTPResult(
                success=success,
                status_code=response.status_code,
                response_body=response.text[:500] if response.text else None,
                webhook_url=self._webhook_url,
                error=None if success else f"HTTP {response.status_code}",
            )

        except Exception as e:
            # Silent failure - log but don't raise
            error_msg = str(e)
            log(
                "HTTP send failed",
                {
                    "error": error_msg,
                    "webhook_url": self._webhook_url,
                },
            )

            return HTTPResult(
                success=False,
                webhook_url=self._webhook_url,
                error=error_msg,
            )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def send(
    payload: Dict[str, Any],
    webhook_url: Optional[str] = None,
    method: str = "POST",
    enrich_from_state: bool = False,
    state_file: Optional[Path] = None,
) -> HTTPResult:
    """Send a payload to an HTTP webhook.

    Convenience function that uses singleton client.

    Args:
        payload: Message data to send (any dict/JSON)
        webhook_url: HTTP endpoint URL (default: from env WEBHOOK_URL)
        method: HTTP method (default: POST)
        enrich_from_state: If True and payload has 'session_id',
                          merges data from conversation_map.json
        state_file: Custom state file path (default: ~/conversation_map.json)

    Returns:
        HTTPResult with success status and response info

    Examples:
        # Simple send
        result = send({"event": "completion", "status": "success"})

        # With state enrichment
        result = send(
            {"session_id": "uuid-123", "transcript_path": "/path"},
            enrich_from_state=True
        )

        # Custom endpoint
        result = send(
            {"data": "value"},
            webhook_url="https://api.example.com/webhook"
        )
    """
    client = HTTPClient.get_client(webhook_url=webhook_url, state_file=state_file)
    return client.send(payload, method=method, enrich_from_state=enrich_from_state)


# =============================================================================
# TRANSCRIPT HELPER
# =============================================================================


def get_last_assistant_response(transcript_path: str) -> Optional[str]:
    """Extract the last assistant response from transcript JSONL."""
    try:
        transcript = Path(transcript_path)
        if not transcript.exists():
            return None

        last_response = None
        with open(transcript, "r") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get("type") == "assistant":
                        message = entry.get("message", {})
                        content = message.get("content", [])
                        for block in content:
                            if block.get("type") == "text":
                                last_response = block.get("text")
                except json.JSONDecodeError:
                    continue
        return last_response
    except Exception:
        return None


# =============================================================================
# CLI INTERFACE
# =============================================================================


def main():
    """CLI entry point for HTTP webhook operations."""
    if len(sys.argv) < 2:
        print("Usage: /app/hooks/integrations/http.py <command> [args]")
        print("")
        print("Commands:")
        print("  check                    Check configuration status")
        print("  check --json             Output status as JSON")
        print("  hook [--demo]            Read Stop event from stdin, send to webhook")
        print("                           --demo: Test mode, prints message and exits")
        print("  send <json>              Send JSON payload to webhook")
        print("  send <json> --enrich     Send with state enrichment")
        print("")
        print("Environment Variables:")
        print("  WEBHOOK_URL             HTTP endpoint URL (required)")
        print("  WEBHOOK_AUTH_HEADER     Auth header name (default: X-Auth-Token)")
        print("  WEBHOOK_AUTH_TOKEN      Auth token value")
        print("  WEBHOOK_TIMEOUT         Request timeout in seconds (default: 30)")
        print("  IS_EVALUATION           Skip sending in evaluation mode")
        print("")
        print("Examples:")
        print("  # Check configuration")
        print("  /app/hooks/integrations/http.py check")
        print("")
        print("  # As Claude Code hook")
        print("  /app/hooks/integrations/http.py hook < stop_event.json")
        print("")
        print("  # Test mode (no actual send)")
        print("  /app/hooks/integrations/http.py hook --demo")
        print("")
        print("  # Manual testing")
        print('  export WEBHOOK_URL="https://api.example.com/webhook"')
        print('  /app/hooks/integrations/http.py send \'{"event": "test"}\'')
        print('  /app/hooks/integrations/http.py send \'{"session_id": "xyz"}\' --enrich')
        sys.exit(1)

    command = sys.argv[1]

    if command == "check":
        # Check configuration status
        integration = HTTPIntegration()
        as_json = "--json" in sys.argv
        integration.print_status(as_json=as_json)
        sys.exit(0 if integration.is_configured else 1)

    elif command == "hook":
        # Hook mode: Read from stdin, enrich, send
        try:
            # Check for demo flag (testing mode)
            if "--demo" in sys.argv:
                log("[DEMO] HTTP hook triggered - webhook integration ready")
                sys.exit(0)

            # Early validation - fail loudly if not configured
            integration = HTTPIntegration()
            if not integration.is_configured:
                missing = integration.get_missing_required()
                error_msg = f"HTTP hook SKIPPED - missing env vars: {missing}"
                log(error_msg, {"integration": "http", "missing": missing})
                # Print to STDOUT so Claude Code shows it
                print(f"\n{'=' * 60}")
                print(f"[HTTP] ERROR: {error_msg}")
                print(f"{'=' * 60}\n")
                sys.exit(0)  # Exit cleanly but warn

            payload = json.load(sys.stdin)

            # Extract last assistant response from transcript
            transcript_path = payload.get("transcript_path", "")
            if transcript_path:
                last_response = get_last_assistant_response(transcript_path)
                if last_response:
                    payload["last_response"] = last_response

            # Add integration identifier
            payload["integration"] = "http"

            # Send with state enrichment
            send(payload, enrich_from_state=True)
            sys.exit(0)
        except Exception:
            sys.exit(0)  # Silent failure for hooks

    elif command == "send":
        if len(sys.argv) < 3:
            print("Error: Missing JSON payload")
            print("Usage: /app/hooks/integrations/http.py send <json> [--enrich]")
            sys.exit(1)

        json_str = sys.argv[2]
        enrich = "--enrich" in sys.argv or "-e" in sys.argv

        try:
            payload = json.loads(json_str)

            if not isinstance(payload, dict):
                print(
                    json.dumps(
                        {
                            "success": False,
                            "error": "Payload must be a JSON object/dict",
                        }
                    )
                )
                sys.exit(1)

            result = send(payload, enrich_from_state=enrich)

            print(
                json.dumps(
                    {
                        "success": result.success,
                        "status_code": result.status_code,
                        "webhook_url": result.webhook_url,
                        "error": result.error,
                    }
                )
            )

            sys.exit(0 if result.success else 1)

        except json.JSONDecodeError as e:
            print(
                json.dumps(
                    {
                        "success": False,
                        "error": f"Invalid JSON: {str(e)}",
                    }
                )
            )
            sys.exit(1)

        except Exception as e:
            print(
                json.dumps(
                    {
                        "success": False,
                        "error": str(e),
                    }
                )
            )
            sys.exit(1)

    else:
        print(f"Error: Unknown command '{command}'")
        print("Usage: /app/hooks/integrations/http.py <command> [args]")
        sys.exit(1)


if __name__ == "__main__":
    main()
