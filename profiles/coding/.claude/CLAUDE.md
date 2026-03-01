# Coding Agent

## Guidelines
- Commit with descriptive messages
- Do NOT create PRs — the system handles that
- Focus on the task, be thorough, test your changes

## Security
- Never handle real credentials, API keys, tokens, or passwords in plaintext
- Reference secrets via environment variables only (e.g. `$MY_API_KEY`, not the value)
- If a task requires credentials, ask the user to configure them as env vars
- Never echo, log, print, or commit secret values
- If you encounter a credential value in context, treat it as an error and stop
