# ingester/config.py
# Environment variable configuration for the publications ingester.
# Adapted from the SEM metadata pipeline config.py.
# Supports both Azure OpenAI (GPT) and Azure Claude (Anthropic) providers.

import os

# ── Azure Claude (Anthropic) — primary provider for ingester ──────────────────
AZURE_CLAUDE_BASE_URL_DEFAULT   = "https://kyage-m5wiv7cf-eastus2.services.ai.azure.com/anthropic"
AZURE_CLAUDE_DEPLOYMENT_DEFAULT = "claude-sonnet-4-6"

# ── Azure OpenAI (GPT) — fallback provider ────────────────────────────────────
AZURE_OPENAI_BASE_URL_DEFAULT   = "https://kyage-m5wiv7cf-eastus2.openai.azure.com/openai/v1/"
AZURE_OPENAI_DEPLOYMENT_DEFAULT = "gpt-4o"


def get_provider() -> str:
    """
    Returns the active provider: 'claude' (default for ingester) or 'openai'.
    Set with: export PROVIDER=claude
    Note: ingester defaults to claude, unlike SEM pipeline which defaults to openai.
    """
    return os.environ.get("PROVIDER", "claude").strip().lower()


def get_azure_base_url() -> str:
    if get_provider() == "claude":
        return os.environ.get("AZURE_CLAUDE_BASE_URL", AZURE_CLAUDE_BASE_URL_DEFAULT).strip().rstrip("/")
    return os.environ.get("AZURE_BASE_URL", AZURE_OPENAI_BASE_URL_DEFAULT).strip()


def get_deployment_name() -> str:
    if get_provider() == "claude":
        return os.environ.get("AZURE_CLAUDE_DEPLOYMENT", AZURE_CLAUDE_DEPLOYMENT_DEFAULT).strip()
    return os.environ.get("AZURE_DEPLOYMENT_NAME", AZURE_OPENAI_DEPLOYMENT_DEFAULT).strip()


def get_api_key() -> str:
    if get_provider() == "claude":
        key = os.environ.get("AZURE_CLAUDE_API_KEY", "").strip()
        if not key:
            raise SystemExit("AZURE_CLAUDE_API_KEY is not set. Run: export AZURE_CLAUDE_API_KEY=your-key")
        return key
    key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
    if not key:
        raise SystemExit("AZURE_OPENAI_API_KEY is not set in your environment.")
    return key
