"""Agent completions MCP tools."""

import json

from hooks.common import log


def register(mcp):
    @mcp.tool()
    def agent_completions(
        prompt: str,
        command: str = "default",
        wait: bool = True,
        stateless: bool = False,
        template_vars: str = "{}",
        context: str = "{}",
    ) -> str:
        """Call the /completions endpoint to invoke the remote agent.

        This tool calls the internal FastAPI /completions endpoint running on localhost.
        Use it to trigger remote agents (e.g., drawio) for tasks like diagram generation.

        Args:
            prompt: The task/specification for the agent
            command: Command preset controlling model selection:
                     - "default": Fast (haiku)
                     - "thinkhard": Balanced (sonnet)
                     - "ultrathink": Best quality (opus)
            wait: If True, waits for completion (default: True)
            stateless: If True, generates fresh Claude session without history (default: False)
            template_vars: JSON object with template variables for prompt rendering
            context: JSON object with context data passed to agent (default: "{}")

        Returns:
            JSON with agent response or acceptance message
        """
        try:
            from hooks.integrations.completions import call_completions

            vars_dict = None
            if template_vars and template_vars != "{}":
                vars_dict = json.loads(template_vars)

            context_dict = None
            if context and context != "{}":
                context_dict = json.loads(context)

            result = call_completions(
                prompt=prompt,
                command=command,
                wait=wait,
                stateless=stateless,
                template_vars=vars_dict,
                context=context_dict,
            )
            return json.dumps(result.to_dict())

        except json.JSONDecodeError as e:
            log("MCP agent_completions JSON parse failed", {"error": str(e)})
            return json.dumps({"success": False, "error": f"Invalid JSON: {str(e)}"})
        except Exception as e:
            log("MCP agent_completions failed", {"error": str(e)})
            return json.dumps({"success": False, "error": str(e)})
