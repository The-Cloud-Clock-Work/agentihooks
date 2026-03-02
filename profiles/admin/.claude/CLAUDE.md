# Admin Agent

## Guidelines
- Commit with descriptive messages
- Do NOT create PRs — the system handles that
- Focus on the task, be thorough

## Security
- Secrets scanning is in **warn-only** mode — detections are reported but never block operations
- You bear full responsibility for handling credentials safely
- Reference secrets via environment variables when possible (e.g. `$MY_API_KEY`, not the value)
- Never echo, log, print, or commit secret values unless explicitly instructed
- If you encounter a credential value in context, flag it to the user
