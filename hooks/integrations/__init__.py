"""External service integrations.

This package contains clients for external services:
- github: GitHub App authentication + git operations
- confluence: Confluence API client
- aws: AWS config parsing
- mailer: SMTP email client
- sqs: AWS SQS messaging with state enrichment
- storage: AWS S3 storage uploads
- webhook: HTTP webhook client
- lambda_invoke: AWS Lambda invocation
- dynamodb: AWS DynamoDB storage
- postgres: PostgreSQL database storage

Integration Configuration:
    All integrations use IntegrationBase for environment variable validation.
    Use `check_all_integrations()` to verify all required env vars are set.

    Example:
        from hooks.integrations import check_all_integrations
        results = check_all_integrations()  # Returns dict of ConfigStatus
"""

from hooks.integrations.base import (
    IntegrationBase,
    IntegrationRegistry,
    ConfigStatus,
    EnvVarStatus,
)

from hooks.integrations.github import (
    GitHubAuth,
    GitOperations,
    requires_github_token,
    get_github_token,
    embed_token_in_url,
    clone_repo,
    create_pr,
)

from hooks.integrations.confluence import (
    ConfluenceClient,
    PageInfo,
)

from hooks.integrations.aws import (
    AWSConfigParser,
    AWSAccount,
    get_aws_profiles,
    get_aws_account_id,
    get_all_aws_accounts,
    find_aws_account,
)

from hooks.integrations.mailer import (
    EmailClient,
    EmailResult,
    EmailConfig,
    EmailIntegration,
    send_email,
    send_markdown_file,
    send_from_config,
    load_email_config,
    load_html_template,
    scan_for_config_files,
    markdown_to_html,
    wrap_html_body,
    parse_recipients,
)

from hooks.integrations.git_diff import (
    get_git_summary,
)

from hooks.integrations.completions import (
    CompletionsClient,
    CompletionResult,
    call_completions,
)

from hooks.integrations.sqs import (
    SQSClient,
    SQSResult,
    SQSIntegration,
    send_message,
    load_state,
)

from hooks.integrations.storage import (
    S3StorageClient,
    StorageIntegration,
    UploadResult,
    upload_path,
)

from hooks.integrations.webhook import (
    HTTPClient,
    HTTPResult,
    HTTPIntegration,
    send as http_send,
)

from hooks.integrations.lambda_invoke import (
    LambdaClient,
    LambdaResult,
    LambdaIntegration,
    invoke as lambda_invoke,
)

from hooks.integrations.dynamodb import (
    DynamoDBClient,
    DynamoDBResult,
    DynamoDBIntegration,
    put_item as dynamodb_put_item,
)

from hooks.integrations.postgres import (
    PostgresClient,
    PostgresResult,
    PostgresIntegration,
    insert as postgres_insert,
    execute as postgres_execute,
)

from hooks.integrations.file_system import (
    DeleteResult,
    delete,
    set_context_dir,
    get_context_dir,
    delete_context_dir,
)

from hooks.integrations.mermaid_validator import (
    MermaidValidator,
    ValidationResult,
    ValidationIssue,
    DiagramInfo,
    validate_markdown_file,
    validate_mermaid_content,
)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def check_all_integrations(print_output: bool = False) -> dict:
    """Check configuration status of all registered integrations.

    Args:
        print_output: If True, print status to stdout

    Returns:
        Dict mapping integration names to their ConfigStatus

    Example:
        from hooks.integrations import check_all_integrations

        # Programmatic check
        results = check_all_integrations()
        for name, status in results.items():
            if not status.is_configured:
                print(f"{name}: Missing {status.missing_required}")

        # With output
        check_all_integrations(print_output=True)
    """
    return IntegrationRegistry.check_all(print_output=print_output)


__all__ = [
    # Integration Base
    "IntegrationBase",
    "IntegrationRegistry",
    "ConfigStatus",
    "EnvVarStatus",
    "check_all_integrations",
    # GitHub Auth
    "GitHubAuth",
    "requires_github_token",
    "get_github_token",
    "embed_token_in_url",
    # Git Operations
    "GitOperations",
    "clone_repo",
    "create_pr",
    # Confluence
    "ConfluenceClient",
    "PageInfo",
    # AWS
    "AWSConfigParser",
    "AWSAccount",
    "get_aws_profiles",
    "get_aws_account_id",
    "get_all_aws_accounts",
    "find_aws_account",
    # Email
    "EmailClient",
    "EmailResult",
    "EmailConfig",
    "EmailIntegration",
    "send_email",
    "send_markdown_file",
    "send_from_config",
    "load_email_config",
    "load_html_template",
    "scan_for_config_files",
    "markdown_to_html",
    "wrap_html_body",
    "parse_recipients",
    # Git Diff
    "get_git_summary",
    # Completions
    "CompletionsClient",
    "CompletionResult",
    "call_completions",
    # SQS
    "SQSClient",
    "SQSResult",
    "SQSIntegration",
    "send_message",
    "load_state",
    # S3 Storage
    "S3StorageClient",
    "StorageIntegration",
    "UploadResult",
    "upload_path",
    # HTTP Webhook
    "HTTPClient",
    "HTTPResult",
    "HTTPIntegration",
    "http_send",
    # Lambda
    "LambdaClient",
    "LambdaResult",
    "LambdaIntegration",
    "lambda_invoke",
    # DynamoDB
    "DynamoDBClient",
    "DynamoDBResult",
    "DynamoDBIntegration",
    "dynamodb_put_item",
    # PostgreSQL
    "PostgresClient",
    "PostgresResult",
    "PostgresIntegration",
    "postgres_insert",
    "postgres_execute",
    # File System
    "DeleteResult",
    "delete",
    "set_context_dir",
    "get_context_dir",
    "delete_context_dir",
    # Mermaid Validator
    "MermaidValidator",
    "ValidationResult",
    "ValidationIssue",
    "DiagramInfo",
    "validate_markdown_file",
    "validate_mermaid_content",
]
