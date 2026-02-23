#!/usr/bin/env python3
"""AWS SQS integration for sending messages with optional state enrichment.

Sends JSON payloads to AWS SQS queues with optional enrichment from a state file.
This enables stateful integrations with external platforms (Teams, Slack, webhooks, etc.)
without embedding platform-specific logic in the agent.

Environment Variables:
    SQS_QUEUE_URL: AWS SQS queue URL (required for sending)
    IS_EVALUATION: Skip sending in evaluation mode (default: false)

State File:
    ~/conversation_map.json: Maps session UUIDs to integration state
    Format: {"uuid": {"conversation_id": "...", "wait": false, ...}}

Usage:
    # Python import
    from hooks.integrations.sqs import send_message

    # Simple send
    result = send_message({"event": "completion", "status": "success"})

    # With state enrichment
    result = send_message(
        {"session_id": "uuid-123", "transcript_path": "/path"},
        enrich_from_state=True
    )

    # CLI
    /app/hooks/integrations/sqs.py send '{"key": "value"}'
    /app/hooks/integrations/sqs.py send '{"session_id": "xyz"}' --enrich
    /app/hooks/integrations/sqs.py check  # Check configuration status
"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

# Add parent directories to path for direct script execution
_script_dir = Path(__file__).resolve().parent
_app_dir = _script_dir.parent.parent  # /app
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))

try:
    import boto3

    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

from hooks.common import log, get_correlation_id
from hooks.integrations.base import IntegrationBase, IntegrationRegistry


# =============================================================================
# INTEGRATION DEFINITION
# =============================================================================


@IntegrationRegistry.register
class SQSIntegration(IntegrationBase):
    """SQS integration configuration checker."""

    INTEGRATION_NAME = "sqs"
    REQUIRED_ENV_VARS = {
        "SQS_QUEUE_URL": "AWS SQS queue URL for sending messages",
    }
    OPTIONAL_ENV_VARS = {
        "IS_EVALUATION": "Skip sending in evaluation mode (default: false)",
        "AWS_PROFILE": "AWS profile to use for credentials",
        "AWS_REGION": "AWS region for SQS queue",
    }


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_STATE_FILE = Path.home() / "conversation_map.json"

# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class SQSResult:
    """Result of SQS send operation."""

    success: bool
    message_id: Optional[str] = None
    queue_url: Optional[str] = None
    error: Optional[str] = None


# =============================================================================
# STATE MANAGEMENT
# =============================================================================


def load_state(session_id: str, state_file: Optional[Path] = None) -> Dict[str, Any]:
    """Load state data for a session from conversation_map.json.

    Uses correlation ID (external UUID) for lookup since the API stores state
    under the external UUID, which may differ from Claude's session ID.

    Args:
        session_id: Session UUID to look up (will be mapped to correlation ID)
        state_file: Custom state file path (default: ~/conversation_map.json)

    Returns:
        Dict with state data, or empty dict if not found
    """
    state_path = state_file or DEFAULT_STATE_FILE

    try:
        if not state_path.exists():
            return {}

        # Use correlation ID (external UUID) for lookup
        correlation_id = get_correlation_id(session_id)

        mappings = json.loads(state_path.read_text())
        state = mappings.get(correlation_id, {})

        # Handle legacy format (string only) - convert to dict
        if isinstance(state, str):
            return {"conversation_id": state, "wait": False}

        return state if isinstance(state, dict) else {}

    except Exception as e:
        log("Failed to load state", {"session_id": session_id, "error": str(e)})
        return {}


# =============================================================================
# SQS CLIENT
# =============================================================================


class SQSClient:
    """AWS SQS client using boto3."""

    _instance: Optional["SQSClient"] = None

    def __init__(
        self,
        queue_url: Optional[str] = None,
        skip_evaluation: bool = True,
        state_file: Optional[Path] = None,
    ):
        """Initialize SQS client.

        Args:
            queue_url: SQS queue URL (default: from env SQS_QUEUE_URL)
            skip_evaluation: Skip sending when IS_EVALUATION=true (default: True)
            state_file: Custom state file path (default: ~/conversation_map.json)
        """
        self._queue_url = queue_url or os.getenv("SQS_QUEUE_URL", "")
        self._skip_evaluation = skip_evaluation
        self._state_file = state_file or DEFAULT_STATE_FILE
        self._sqs_client = None

        # Check if we should skip (evaluation mode)
        self._is_evaluation = os.getenv("IS_EVALUATION", "false").lower() == "true"

    @classmethod
    def get_client(
        cls,
        queue_url: Optional[str] = None,
        skip_evaluation: bool = True,
        state_file: Optional[Path] = None,
    ) -> "SQSClient":
        """Get singleton instance."""
        if cls._instance is None or queue_url or state_file:
            cls._instance = cls(
                queue_url=queue_url,
                skip_evaluation=skip_evaluation,
                state_file=state_file,
            )
        return cls._instance

    @classmethod
    def clear_cache(cls) -> None:
        """Clear cached instance (for testing)."""
        cls._instance = None

    @property
    def sqs(self):
        """Lazy-load boto3 SQS client."""
        if self._sqs_client is None:
            if not BOTO3_AVAILABLE:
                raise ImportError("boto3 is required for SQS integration")
            self._sqs_client = boto3.client("sqs")
        return self._sqs_client

    def should_skip(self) -> bool:
        """Check if sending should be skipped."""
        # Skip if no queue URL configured
        if not self._queue_url:
            log(
                "SQS send skipped: SQS_QUEUE_URL not configured",
                {"integration": "sqs", "reason": "missing_config"},
            )
            return True

        # Skip if evaluation mode
        if self._skip_evaluation and self._is_evaluation:
            log(
                "SQS send skipped: IS_EVALUATION=true",
                {"integration": "sqs", "reason": "evaluation_mode"},
            )
            return True

        return False

    def send_message(
        self,
        payload: Dict[str, Any],
        enrich_from_state: bool = False,
    ) -> SQSResult:
        """Send a message to SQS with optional state enrichment.

        Args:
            payload: Message data to send
            enrich_from_state: If True and payload has 'session_id',
                              merges data from conversation_map.json

        Returns:
            SQSResult with success status and message ID
        """
        # Check if we should skip sending
        if self.should_skip():
            return SQSResult(
                success=True,
                queue_url=self._queue_url or "not-configured",
            )

        try:
            # Enrich with state if requested
            enriched_payload = payload.copy()

            if enrich_from_state and "session_id" in payload:
                session_id = payload["session_id"]
                state = load_state(session_id, self._state_file)

                # Check if wait=true (skip SQS for synchronous responses)
                if state.get("wait", False):
                    log(
                        "Skipping SQS send",
                        {
                            "reason": "wait=true (synchronous response)",
                            "session_id": session_id,
                        },
                    )
                    return SQSResult(
                        success=True,
                        queue_url=self._queue_url,
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

            # Send to SQS
            message_body = json.dumps(enriched_payload)

            log(
                "Sending to SQS",
                {
                    "queue_url": self._queue_url,
                    "payload_size": len(message_body),
                },
            )

            response = self.sqs.send_message(
                QueueUrl=self._queue_url,
                MessageBody=message_body,
            )

            message_id = response.get("MessageId")

            log(
                "SQS send succeeded",
                {
                    "message_id": message_id,
                    "queue_url": self._queue_url,
                },
            )

            return SQSResult(
                success=True,
                message_id=message_id,
                queue_url=self._queue_url,
            )

        except Exception as e:
            # Silent failure - log but don't raise
            error_msg = str(e)
            log(
                "SQS send failed",
                {
                    "error": error_msg,
                    "queue_url": self._queue_url,
                },
            )

            return SQSResult(
                success=False,
                queue_url=self._queue_url,
                error=error_msg,
            )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def send_message(
    payload: Dict[str, Any],
    queue_url: Optional[str] = None,
    enrich_from_state: bool = False,
    state_file: Optional[Path] = None,
) -> SQSResult:
    """Send a message to SQS with optional state enrichment.

    Convenience function that uses singleton client.

    Args:
        payload: Message data to send (any dict/JSON)
        queue_url: SQS queue URL (default: from env SQS_QUEUE_URL)
        enrich_from_state: If True and payload has 'session_id',
                          merges data from conversation_map.json
        state_file: Custom state file path (default: ~/conversation_map.json)

    Returns:
        SQSResult with success status and message ID

    Examples:
        # Simple send
        result = send_message({"event": "completion", "status": "success"})

        # With state enrichment
        result = send_message(
            {"session_id": "uuid-123", "transcript_path": "/path"},
            enrich_from_state=True
        )

        # Custom queue
        result = send_message(
            {"data": "value"},
            queue_url="https://sqs.us-west-2.amazonaws.com/123/queue"
        )
    """
    client = SQSClient.get_client(queue_url=queue_url, state_file=state_file)
    return client.send_message(payload, enrich_from_state=enrich_from_state)


# =============================================================================
# CLI INTERFACE
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


def main():
    """CLI entry point for SQS operations."""
    if len(sys.argv) < 2:
        print("Usage: /app/hooks/integrations/sqs.py <command> [args]")
        print("")
        print("Commands:")
        print("  check                    Check configuration status")
        print("  check --json             Output status as JSON")
        print(
            "  hook [--demo]            Read Stop event from stdin, enrich, send to SQS"
        )
        print("                           --demo: Test mode, prints message and exits")
        print("  send <json>              Send JSON message to SQS")
        print("  send <json> --enrich     Send with state enrichment")
        print("")
        print("Environment Variables:")
        print("  SQS_QUEUE_URL           SQS queue URL (required)")
        print("  IS_EVALUATION           Skip sending in evaluation mode")
        print("")
        print("Examples:")
        print("  # Check configuration")
        print("  /app/hooks/integrations/sqs.py check")
        print("")
        print("  # As Claude Code hook")
        print("  /app/hooks/integrations/sqs.py hook < stop_event.json")
        print("")
        print("  # Test mode (no actual send)")
        print("  /app/hooks/integrations/sqs.py hook --demo")
        print("")
        print("  # Manual testing")
        print('  export SQS_QUEUE_URL="https://sqs.us-west-2.amazonaws.com/123/queue"')
        print('  /app/hooks/integrations/sqs.py send \'{"event": "test"}\'')
        print(
            '  /app/hooks/integrations/sqs.py send \'{"session_id": "xyz"}\' --enrich'
        )
        sys.exit(1)

    command = sys.argv[1]

    if command == "check":
        # Check configuration status
        integration = SQSIntegration()
        as_json = "--json" in sys.argv
        integration.print_status(as_json=as_json)
        sys.exit(0 if integration.is_configured else 1)

    elif command == "hook":
        # Hook mode: Read from stdin, enrich, send
        try:
            # Check for demo flag (testing mode)
            if "--demo" in sys.argv:
                log("[DEMO] SQS hook triggered - queue integration ready")
                sys.exit(0)

            # Early validation - fail loudly if not configured
            integration = SQSIntegration()
            if not integration.is_configured:
                missing = integration.get_missing_required()
                error_msg = f"SQS hook SKIPPED - missing env vars: {missing}"
                log(error_msg, {"integration": "sqs", "missing": missing})
                # Print to STDOUT so Claude Code shows it
                print(f"\n{'='*60}")
                print(f"[SQS] ERROR: {error_msg}")
                print(f"{'='*60}\n")
                sys.exit(0)  # Exit cleanly but warn

            payload = json.load(sys.stdin)

            # Extract last assistant response from transcript
            transcript_path = payload.get("transcript_path", "")
            if transcript_path:
                last_response = get_last_assistant_response(transcript_path)
                if last_response:
                    payload["last_response"] = last_response

            # Send with state enrichment
            send_message(payload, enrich_from_state=True)
            sys.exit(0)
        except Exception:
            sys.exit(0)  # Silent failure for hooks

    elif command == "send":
        if len(sys.argv) < 3:
            print("Error: Missing JSON payload")
            print("Usage: /app/hooks/integrations/sqs.py send <json> [--enrich]")
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

            result = send_message(payload, enrich_from_state=enrich)

            print(
                json.dumps(
                    {
                        "success": result.success,
                        "message_id": result.message_id,
                        "queue_url": result.queue_url,
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
        print("Usage: /app/hooks/integrations/sqs.py <command> [args]")
        sys.exit(1)


if __name__ == "__main__":
    main()
