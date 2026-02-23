"""Lambda compute MCP tools."""

import json

from hooks.common import log


def register(mcp):
    @mcp.tool()
    def lambda_invoke_function(
        payload: str,
        function_name: str = "",
        async_invoke: bool = False,
        enrich: bool = False,
    ) -> str:
        """Invoke an AWS Lambda function with JSON payload.

        Invokes Lambda with optional state enrichment. Supports both synchronous
        (RequestResponse) and asynchronous (Event) invocation types.

        Args:
            payload: JSON string with event data to send to Lambda
            function_name: Lambda function ARN or name (default: from LAMBDA_FUNCTION_NAME env var)
            async_invoke: If True, use Event invocation type (fire and forget, default: False)
            enrich: If True, enriches payload with state from conversation_map.json (default: False)

        Returns:
            JSON with success status, status_code, response_payload, and invocation_type
        """
        try:
            from hooks.integrations.lambda_invoke import invoke

            payload_dict = json.loads(payload)

            result = invoke(
                payload=payload_dict,
                function_name=function_name if function_name else None,
                async_invoke=async_invoke,
                enrich_from_state=enrich,
            )

            return json.dumps({
                "success": result.success,
                "status_code": result.status_code,
                "function_name": result.function_name,
                "invocation_type": result.invocation_type,
                "response_payload": result.response_payload,
                "error": result.error,
            })

        except json.JSONDecodeError as e:
            log("MCP lambda_invoke_function JSON parse failed", {"error": str(e)})
            return json.dumps({"success": False, "error": f"Invalid JSON: {str(e)}"})
        except Exception as e:
            log("MCP lambda_invoke_function failed", {"error": str(e)})
            return json.dumps({"success": False, "error": str(e)})
