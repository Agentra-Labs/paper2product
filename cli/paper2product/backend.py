from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from .errors import AgentExecutionError

OPENAI_COMPATIBLE_BACKEND = "openai_compatible"
AGENTICA_BACKEND = "agentica"
APODEX_BACKEND = "apodex"
DEFAULT_OPENAI_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_DIRECT_TIMEOUT_SECONDS = 240.0

VALID_BACKENDS = {OPENAI_COMPATIBLE_BACKEND, AGENTICA_BACKEND, APODEX_BACKEND}


def get_execution_backend_name() -> str:
    configured = os.getenv("EXECUTION_BACKEND", "").strip().lower()
    if configured in VALID_BACKENDS:
        return configured
    # Auto-detect: Apodex key takes priority if explicitly set,
    # then fall back to OpenAI/OpenRouter, then Agentica
    if os.getenv("APODEX_API_KEY"):
        return APODEX_BACKEND
    if os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY"):
        return OPENAI_COMPATIBLE_BACKEND
    return AGENTICA_BACKEND


def normalize_model_name(model: str) -> str:
    return model.removeprefix("openrouter:")


def _direct_api_key() -> str:
    return os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY", "")


def _direct_base_url() -> str:
    return os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL)


def _direct_timeout_seconds() -> float:
    raw_value = os.getenv("DIRECT_BACKEND_TIMEOUT_SECONDS", str(DEFAULT_DIRECT_TIMEOUT_SECONDS))
    try:
        value = float(raw_value)
    except ValueError:
        return DEFAULT_DIRECT_TIMEOUT_SECONDS
    return max(10.0, value)


def _extract_message_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices", [])
    if not choices:
        raise AgentExecutionError("Direct backend returned no choices.")

    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)
    raise AgentExecutionError("Direct backend returned unsupported message content.")


def _provider_host(base_url: str) -> str:
    parsed = urlparse(base_url)
    return parsed.netloc or base_url


def _provider_slug_hint(base_url: str, model: str) -> str:
    host = _provider_host(base_url)
    if "openrouter.ai" in host:
        return ""
    if "/" in model:
        return (
            " The configured provider may not accept OpenRouter-style model slugs "
            f"like '{model}'. Try a provider-native model name via the CLI argument "
            "or PAPER2PRODUCT_MODEL in .env."
        )
    return ""


def _response_error_text(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        body = response.text.strip()
        return body[:400] if body else ""

    if isinstance(payload, dict):
        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if isinstance(value, str):
                return value[:400]
            if isinstance(value, dict):
                nested = value.get("message") or value.get("detail")
                if isinstance(nested, str):
                    return nested[:400]
    return str(payload)[:400]


@dataclass
class OpenAICompatibleBackend:
    base_url: str
    api_key: str
    timeout_seconds: float

    async def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        phase: str,
        max_tokens: int | None = None,
    ) -> str:
        if not self.api_key:
            raise AgentExecutionError(
                "OpenAI-compatible backend selected but OPENAI_API_KEY or "
                "OPENROUTER_API_KEY is not configured."
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if "openrouter.ai" in self.base_url:
            headers["HTTP-Referer"] = "https://github.com/Ash-Blanc/paper2product"
            headers["X-Title"] = "paper2product"

        payload: dict[str, Any] = {
            "model": normalize_model_name(model),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        timeout = httpx.Timeout(self.timeout_seconds, connect=min(self.timeout_seconds, 20.0))
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout,
        ) as client:
            response = await client.post("/chat/completions", json=payload)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                details = _response_error_text(response)
                provider = _provider_host(self.base_url)
                detail_suffix = f" Response body: {details}" if details else ""
                raise AgentExecutionError(
                    f"{phase} request was rejected by {provider} "
                    f"(HTTP {response.status_code}) using model '{normalize_model_name(model)}'."
                    f"{_provider_slug_hint(self.base_url, normalize_model_name(model))}"
                    f"{detail_suffix}"
                ) from exc

        text = _extract_message_text(response.json()).strip()
        if not text:
            raise AgentExecutionError(f"{phase} returned empty output.")
        return text


def build_openai_compatible_backend() -> OpenAICompatibleBackend:
    return OpenAICompatibleBackend(
        base_url=_direct_base_url(),
        api_key=_direct_api_key(),
        timeout_seconds=_direct_timeout_seconds(),
    )
