# src/metadata_tagging/openai_client.py
from config import get_api_key, get_azure_base_url, get_provider, get_deployment_name


# ── Anthropic response shim ────────────────────────────────────────────────────
# Makes Anthropic responses look like OpenAI responses so the rest of the
# pipeline can call client.chat.completions.create() regardless of provider.

class _AnthropicMessage:
    def __init__(self, content: str):
        self.content = content

class _AnthropicChoice:
    def __init__(self, content: str, stop_reason: str):
        self.message       = _AnthropicMessage(content)
        self.finish_reason = stop_reason

class _AnthropicResponse:
    def __init__(self, content: str, stop_reason: str):
        self.choices = [_AnthropicChoice(content, stop_reason)]

class _AnthropicCompletions:
    def __init__(self, client, deployment: str):
        self._client     = client
        self._deployment = deployment

    def create(self, model=None, messages=None, max_completion_tokens=4000,
               max_tokens=None, temperature=None, **kwargs):
        # Separate system message from user/assistant messages
        system_msg = None
        filtered   = []
        for m in (messages or []):
            if m.get("role") == "system":
                system_msg = m["content"]
            else:
                filtered.append(m)

        # Anthropic uses max_tokens, not max_completion_tokens
        limit = max_tokens or max_completion_tokens or 4000

        call_kwargs = dict(
            model      = model or self._deployment,
            messages   = filtered,
            max_tokens = limit,
        )
        if system_msg:
            call_kwargs["system"] = system_msg
        if temperature is not None:
            call_kwargs["temperature"] = temperature

        # Use streaming to avoid timeout on large requests
        # Anthropic requires streaming for operations that may take >10 minutes
        text_content = ""
        stop_reason  = "stop"
        with self._client.messages.stream(**call_kwargs) as stream:
            for text in stream.text_stream:
                text_content += text
            final = stream.get_final_message()
            stop_reason = final.stop_reason or "stop"

        return _AnthropicResponse(text_content, stop_reason)


class _AnthropicChat:
    def __init__(self, client, deployment: str):
        self.completions = _AnthropicCompletions(client, deployment)


def _convert_responses_to_anthropic(messages: list) -> list:
    """
    Convert OpenAI Responses API message format to Anthropic messages format.

    OpenAI Responses API uses:
      {"type": "input_text", "text": "..."}
      {"type": "input_image", "image_url": "data:image/png;base64,...", "detail": "auto"}

    Anthropic uses:
      {"type": "text", "text": "..."}
      {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}}
    """
    converted = []
    for msg in messages:
        role    = msg.get("role", "user")
        content = msg.get("content", [])
        new_content = []
        for block in content:
            btype = block.get("type", "")
            if btype == "input_text":
                new_content.append({"type": "text", "text": block.get("text", "")})
            elif btype == "input_image":
                image_url = block.get("image_url", "")
                # Parse data URL: data:image/png;base64,<data>
                if image_url.startswith("data:"):
                    header, data = image_url.split(",", 1)
                    media_type   = header.split(":")[1].split(";")[0]  # e.g. image/png
                else:
                    data       = image_url
                    media_type = "image/png"
                new_content.append({
                    "type": "image",
                    "source": {
                        "type":       "base64",
                        "media_type": media_type,
                        "data":       data,
                    },
                })
            else:
                # Pass through unknown block types unchanged
                new_content.append(block)
        converted.append({"role": role, "content": new_content})
    return converted


class _AnthropicResponses:
    """
    Shim for client.responses.create() — translates OpenAI Responses API
    calls (used by pipeline_tag_images.py) into Anthropic messages format.
    """
    def __init__(self, client, deployment: str):
        self._client     = client
        self._deployment = deployment

    def create(self, model=None, input=None, max_completion_tokens=4000,
               max_tokens=None, **kwargs):
        messages = _convert_responses_to_anthropic(input or [])

        # Separate system message if present
        system_msg = None
        filtered   = []
        for m in messages:
            if m.get("role") == "system":
                system_msg = m["content"]
                if isinstance(system_msg, list):
                    system_msg = " ".join(b.get("text", "") for b in system_msg)
            else:
                filtered.append(m)

        limit = max_tokens or max_completion_tokens or 4000

        call_kwargs = dict(
            model      = model or self._deployment,
            messages   = filtered,
            max_tokens = limit,
        )
        if system_msg:
            call_kwargs["system"] = system_msg

        # Use streaming to avoid timeout on large requests
        text_content = ""
        stop_reason  = "stop"
        with self._client.messages.stream(**call_kwargs) as stream:
            for text in stream.text_stream:
                text_content += text
            final = stream.get_final_message()
            stop_reason = final.stop_reason or "stop"

        return _AnthropicResponse(text_content, stop_reason)


class _AnthropicClientWrapper:
    """Wraps AnthropicFoundry to look like openai.OpenAI to the pipeline."""
    def __init__(self, client, deployment: str):
        self.chat      = _AnthropicChat(client, deployment)
        self.responses = _AnthropicResponses(client, deployment)


# ── Factory ────────────────────────────────────────────────────────────────────

def make_client(timeout: float = 120.0):
    """
    Returns a client for the active provider, selected via PROVIDER env var.

      export PROVIDER=openai   # default — Azure OpenAI (GPT)
      export PROVIDER=claude   # Azure Claude via Microsoft Foundry

    Both return an object with a .chat.completions.create() interface
    so the rest of the pipeline works unchanged regardless of provider.
    """
    provider   = get_provider()
    base_url   = get_azure_base_url()
    api_key    = get_api_key()
    deployment = get_deployment_name()

    print(f"[client] Provider: {provider} | Deployment: {deployment}")

    if provider == "claude":
        # Azure Foundry exposes Claude via the AnthropicFoundry client
        # which handles the Azure-specific auth and endpoint routing.
        from anthropic import AnthropicFoundry
        client = AnthropicFoundry(
            api_key  = api_key,
            base_url = base_url,
        )
        return _AnthropicClientWrapper(client, deployment)

    # Default: OpenAI-compatible client
    from openai import OpenAI
    return OpenAI(
        api_key  = api_key,
        base_url = base_url,
        timeout  = timeout,
    )
