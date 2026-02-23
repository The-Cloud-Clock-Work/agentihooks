"""Smith command builder MCP tools."""

import json

from hooks.common import log


def register(mcp):
    @mcp.tool()
    def smith_list_commands() -> str:
        """List all available command presets from commands.json.

        Returns:
            JSON with list of command names and their configurations
        """
        try:
            from agenticore.command_builder import CommandBuilder

            builder = CommandBuilder()
            commands = builder.list_commands()

            details = {}
            for cmd_name in commands:
                config = builder.get_command_config(cmd_name)
                prompt_file = builder.get_prompt_file(cmd_name)
                details[cmd_name] = {
                    "has_prompt": prompt_file is not None,
                    "prompt_file": str(prompt_file) if prompt_file else None,
                    "command_preview": config.get("command", [])[:5] if config else [],
                }

            return json.dumps({
                "success": True,
                "count": len(commands),
                "commands": commands,
                "details": details,
            })

        except Exception as e:
            log("MCP smith_list_commands failed", {"error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def smith_get_prompt(command_name: str = "default") -> str:
        """Get the prompt content for a command preset.

        Reads the markdown prompt file associated with a command.

        Args:
            command_name: Command preset name (default: "default")

        Returns:
            JSON with prompt content, file path, and character count
        """
        try:
            from agenticore.command_builder import CommandBuilder

            builder = CommandBuilder()
            prompt_content = builder.read_prompt(command_name)
            prompt_file = builder.get_prompt_file(command_name)

            if prompt_content:
                return json.dumps({
                    "success": True,
                    "command_name": command_name,
                    "prompt_file": str(prompt_file) if prompt_file else None,
                    "content": prompt_content,
                    "char_count": len(prompt_content),
                })
            else:
                return json.dumps({
                    "success": True,
                    "command_name": command_name,
                    "found": False,
                    "error": f"No prompt file found for command '{command_name}'",
                })

        except Exception as e:
            log("MCP smith_get_prompt failed", {"command_name": command_name, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def smith_build_command(
        command_name: str = "default",
        parameters: str = "",
        template_vars: str = "{}",
        inject_prompt: bool = True,
    ) -> str:
        """Build a Claude command array with prompt injection.

        Builds the complete command array from commands.json with:
        - Prompt injection from {command_name}.md
        - Template variable rendering ({{VAR}} placeholders)
        - User parameters appended

        Args:
            command_name: Command preset name from commands.json (default: "default")
            parameters: User task/prompt - comma-separated or JSON array
            template_vars: JSON object with template variables (e.g., '{"USER_NAME": "John"}')
            inject_prompt: Whether to inject .md prompt into --system-prompt (default: True)

        Returns:
            JSON with command array, can be executed with subprocess
        """
        try:
            from agenticore.command_builder import CommandBuilder

            builder = CommandBuilder()

            params_list = None
            if parameters:
                if parameters.strip().startswith("["):
                    params_list = json.loads(parameters)
                else:
                    params_list = [p.strip() for p in parameters.split(",") if p.strip()]

            vars_dict = None
            if template_vars and template_vars != "{}":
                vars_dict = json.loads(template_vars)

            cmd = builder.build_command(
                command_name=command_name,
                parameters=params_list,
                template_vars=vars_dict,
                inject_prompt=inject_prompt,
            )

            return json.dumps({
                "success": True,
                "command_name": command_name,
                "command": cmd,
                "command_str": " ".join(cmd[:5]) + "..." if len(cmd) > 5 else " ".join(cmd),
                "parameters": params_list,
                "template_vars": vars_dict,
                "inject_prompt": inject_prompt,
            })

        except json.JSONDecodeError as e:
            log("MCP smith_build_command JSON parse failed", {"error": str(e)})
            return json.dumps({"success": False, "error": f"Invalid JSON: {str(e)}"})
        except Exception as e:
            log("MCP smith_build_command failed", {"command_name": command_name, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def smith_execute(
        command_name: str = "default",
        parameters: str = "",
        template_vars: str = "{}",
        cwd: str = "",
        timeout: int = 120,
    ) -> str:
        """Build and execute a Claude command synchronously (SHORT TASKS ONLY).

        WARNING: This is BLOCKING and will hang for long-running tasks!
        USE agent_completions INSTEAD for tasks that may take > 2 minutes.

        Args:
            command_name: Command preset name from commands.json (default: "default")
            parameters: User task/prompt - comma-separated or JSON array
            template_vars: JSON object with template variables
            cwd: Working directory (default: /app/package or evaluation dir)
            timeout: Timeout in seconds (default: 120, max recommended: 180)

        Returns:
            JSON with exit_code, stdout, stderr, and duration_ms
        """
        try:
            import subprocess
            import time
            from agenticore.command_builder import CommandBuilder
            from agenticore.settings import settings

            builder = CommandBuilder()

            params_list = None
            if parameters:
                if parameters.strip().startswith("["):
                    params_list = json.loads(parameters)
                else:
                    params_list = [p.strip() for p in parameters.split(",") if p.strip()]

            vars_dict = None
            if template_vars and template_vars != "{}":
                vars_dict = json.loads(template_vars)

            cmd = builder.build_command(
                command_name=command_name,
                parameters=params_list,
                template_vars=vars_dict,
                inject_prompt=True,
            )

            effective_cwd = cwd
            if not effective_cwd:
                if command_name == "evaluation":
                    effective_cwd = "/app/evaluation"
                else:
                    effective_cwd = settings.current_app_dir

            start_time = time.time()
            try:
                result = subprocess.run(
                    cmd,
                    cwd=effective_cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                duration_ms = int((time.time() - start_time) * 1000)

                return json.dumps({
                    "success": True,
                    "exit_code": result.returncode,
                    "stdout": result.stdout[:10000] if result.stdout else "",
                    "stderr": result.stderr[:2000] if result.stderr else "",
                    "duration_ms": duration_ms,
                    "command_name": command_name,
                    "timed_out": False,
                })

            except subprocess.TimeoutExpired:
                duration_ms = int((time.time() - start_time) * 1000)
                return json.dumps({
                    "success": False,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Command timed out after {timeout}s",
                    "duration_ms": duration_ms,
                    "command_name": command_name,
                    "timed_out": True,
                })

        except json.JSONDecodeError as e:
            log("MCP smith_execute JSON parse failed", {"error": str(e)})
            return json.dumps({"success": False, "error": f"Invalid JSON: {str(e)}"})
        except Exception as e:
            log("MCP smith_execute failed", {"command_name": command_name, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})
