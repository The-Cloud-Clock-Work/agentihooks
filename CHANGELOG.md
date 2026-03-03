# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] - 2026-03-03

### Added

- **Admin profile** (`profiles/admin/`) — minimal guardrails, secrets warn-only mode.

### Removed

- **`scripts/agent_hub.py`** — agent provisioning moved to agenticore (clones agentihub directly, no build step needed).
- **Publishing profile** (`profiles/publishing/`) — migrated to standalone K8s app in agentihub. Provisioned directly by agenticore.

## [0.1.0] - 2026-02-23

### Added

- Hook system processing all 10 Claude Code lifecycle events
- Modular MCP tool server with 45 tools across 12 categories
- Category-based tool filtering via `MCP_CATEGORIES` env var
- Profile composition system with base settings + per-profile overrides
- Build script for generating profile artifacts (`scripts/build_profiles.py`)
- Integration clients: GitHub, Confluence, AWS, Email, SQS, S3, Webhook, Lambda, DynamoDB, PostgreSQL
- Observability: transcript logging, metrics collection, container log tailing (Docker/K8s/ECS)
- Cross-session tool error memory (learn from past failures)
- Persistent agent memory via Redis + JSONL fallback
- Two default profiles: `default` and `coding`
