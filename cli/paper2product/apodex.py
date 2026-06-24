"""Apodex backend — OpenAI-compatible deep research API.

Apodex provides three model tiers with built-in web search during reasoning:
  - apodex-1-0-deep-research  (fast, source-grounded)
  - apodex-1-0-deep-reasoning (deeper analysis + inference)
  - apodex-1-0-deep-discovery (highest rigor, agent-team orchestration)

Because Apodex handles web search internally, the pipeline can skip the
Serper/Exa search layer entirely when this backend is active.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from .errors import AgentExecutionError

APODEX_BACKEND = "apodex"
APODEX_BASE_URL = "https://api.apodex.ai"
APODEX_DEFAULT_TIMEOUT_SECONDS = 300.0  # deep research takes time

# Model tiers — each phase maps to the tier that fits its cognitive load
APODEX_MODEL_RESEARCH = "apodex-1-0-deep-research"
APODEX_MODEL_REASONING = "apodex-1-0-deep-reasoning"
APODEX_MODEL_DISCOVERY = "apodex-1-0-deep-discovery"

# Phase → model tier mapping
APODEX_PHASE_MODELS: dict[str, str] = {
    "technical primitive extraction": APODEX_MODEL_REASONING,
    "pain scanner": APODEX_MODEL_RESEARCH,
    "infrastructure inversion": APODEX_MODEL_REASONING,
    "temporal arbitrage": APODEX_MODEL_RESEARCH,
    "compound synthesis": APODEX_MODEL_REASONING,
    "structural simulation": APODEX_MODEL_REASONING,
    "final synthesis": APODEX_MODEL_DISCOVERY,
    "quality review": APODEX_MODEL_REASONING,
    "quality repair": APODEX_MODEL_REASONING,
    "paper search: crawling": APODEX_MODEL_RESEARCH,
    "paper search: selection": APODEX_MODEL_RESEARCH,
    "code skimming": APODEX_MODEL_RESEARCH,
}

# Default model when no phase-specific mapping is found
APODEX_DEFAULT_MODEL = APODEX_MODEL_RESEARCH


def _apodex_api_key() -> str:
    return os.getenv("APODEX_API_KEY", "").strip()


def _apodex_base_url() -> str:
    return os.getenv("APODEX_BASE_URL", APODEX_BASE_URL).strip().rstrip("/")


def _apodex_timeout_seconds() -> float:
    raw = os.getenv("APODEX_TIMEOUT_SECONDS", str(APODEX_DEFAULT_TIMEOUT_SECONDS))
    try:
        return max(30.0, float(raw))
    except ValueError:
        return APODEX_DEFAULT_TIMEOUT_SECONDS


def apodex_configured() -> bool:
    return bool(_apodex_api_key())


def get_apodex_phase_model(phase: str) -> str:
    return APODEX_PHASE_MODELS.get(phase, APODEX_DEFAULT_MODEL)


def _extract_apodex_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices", [])
    if not choices:
        raise AgentExecutionError("Apodex returned no choices.")
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    raise AgentExecutionError("Apodex returned unsupported message content.")


def _apodex_error_text(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        body = response.text.strip()
        return body[:400] if body else ""
    if isinstance(payload, dict):
        err = payload.get("error", {})
        if isinstance(err, dict):
            msg = err.get("message", "")
            if msg:
                return str(msg)[:400]
        msg = payload.get("message", "")
        if msg:
            return str(msg)[:400]
    return str(payload)[:400]


@dataclass
class ApodexBackend:
    base_url: str
    api_key: str
    timeout_seconds: float

    async def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        phase: str,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if not self.api_key:
            raise AgentExecutionError(
                "Apodex backend selected but APODEX_API_KEY is not configured."
            )

        # Pick the right model tier for this phase
        effective_model = model or get_apodex_phase_model(phase)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": effective_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,  # non-streaming for pipeline integration
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        timeout = httpx.Timeout(
            self.timeout_seconds, connect=min(self.timeout_seconds, 20.0)
        )
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout,
        ) as client:
            response = await client.post("/v1/chat/completions", json=payload)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                details = _apodex_error_text(response)
                detail_suffix = f" Response body: {details}" if details else ""
                raise AgentExecutionError(
                    f"{phase} request was rejected by Apodex "
                    f"(HTTP {response.status_code}) using model '{effective_model}'."
                    f"{detail_suffix}"
                ) from exc

        text = _extract_apodex_content(response.json()).strip()
        if not text:
            raise AgentExecutionError(f"{phase} returned empty output from Apodex.")
        return text


def build_apodex_backend() -> ApodexBackend:
    return ApodexBackend(
        base_url=_apodex_base_url(),
        api_key=_apodex_api_key(),
        timeout_seconds=_apodex_timeout_seconds(),
    )
