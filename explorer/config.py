# ingester/config.py
# Environment variable configuration for the publications ingester.
# Adapted from the SEM metadata pipeline config.py.
# Supports both Azure OpenAI (GPT) and Azure Claude (Anthropic) providers.
#
# Configuration is loaded from a .env file if present (for local development),
# or from environment variables (for deployment). See .env.example for the
# required variables.

import os
from dotenv import load_dotenv

load_dotenv()  # loads .env if present; does nothing if absent

# ── Azure Claude (Anthropic) — primary provider for ingester ──────────────────
AZURE_CLAUDE_DEPLOYMENT_DEFAULT = "claude-sonnet-4-6"

# ── Azure OpenAI (GPT) — fallback provider ────────────────────────────────────
AZURE_OPENAI_DEPLOYMENT_DEFAULT = "gpt-4o"

def get_provider() -> str:
    """
    Returns the active provider: 'claude' (default for ingester) or 'openai'.
    Set with: export PROVIDER=claude  or  PROVIDER=claude in .env
    """
    return os.environ.get("PROVIDER", "claude").strip().lower()

def get_azure_base_url() -> str:
    if get_provider() == "claude":
        url = os.environ.get("AZURE_CLAUDE_BASE_URL", "").strip().rstrip("/")
        if not url:
            raise SystemExit("AZURE_CLAUDE_BASE_URL is not set. Add it to .env or run: export AZURE_CLAUDE_BASE_URL=your-endpoint")
        return url
    url = os.environ.get("AZURE_BASE_URL", "").strip()
    if not url:
        raise SystemExit("AZURE_BASE_URL is not set. Add it to .env or run: export AZURE_BASE_URL=your-endpoint")
    return url

def get_deployment_name() -> str:
    if get_provider() == "claude":
        return os.environ.get("AZURE_CLAUDE_DEPLOYMENT", AZURE_CLAUDE_DEPLOYMENT_DEFAULT).strip()
    return os.environ.get("AZURE_DEPLOYMENT_NAME", AZURE_OPENAI_DEPLOYMENT_DEFAULT).strip()

def get_api_key() -> str:
    if get_provider() == "claude":
        key = os.environ.get("AZURE_CLAUDE_API_KEY", "").strip()
        if not key:
            raise SystemExit("AZURE_CLAUDE_API_KEY is not set. Add it to .env or run: export AZURE_CLAUDE_API_KEY=your-key")
        return key
    key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
    if not key:
        raise SystemExit("AZURE_OPENAI_API_KEY is not set. Add it to .env or run: export AZURE_OPENAI_API_KEY=your-key")
    return key