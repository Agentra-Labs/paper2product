from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

import httpx

SearchIntent = Literal["fresh", "fast"]
SearchProvider = Literal["serper", "exa"]

DEFAULT_RESULT_LIMIT = 5
DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_MAX_CALLS_PER_TOOL = 2
_SEARCH_CACHE: dict[tuple[str, SearchIntent, str], SearchResponse] = {}
FRESHNESS_HINTS = (
    "latest",
    "recent",
    "today",
    "current",
    "currently",
    "trend",
    "trends",
    "news",
    "funding",
    "raised",
    "pricing",
    "price",
    "market",
    "regulation",
    "regulatory",
    "incumbent",
    "competitor",
    "competitors",
    "company",
    "companies",
    "startup",
    "startups",
    "buyer",
    "buyers",
    "customer",
    "customers",
    "launch",
    "launched",
    "2024",
    "2025",
    "2026",
)


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    provider: SearchProvider
    published_at: str | None = None

    @property
    def domain(self) -> str:
        return urlparse(self.url).netloc or self.url


@dataclass(frozen=True)
class SearchResponse:
    query: str
    intent: SearchIntent
    provider: SearchProvider | None
    results: list[SearchResult]
    errors: list[str] = field(default_factory=list)


@dataclass
class SearchTrace:
    section_name: str
    entries: list[SearchResponse] = field(default_factory=list)
    calls_used: int = 0
    budget_exhausted: bool = False

    def record(self, response: SearchResponse) -> None:
        if response.results:
            self.entries.append(response)

    def render_markdown(self, *, max_sources: int = 6) -> str:
        unique_sources: list[tuple[SearchResult, SearchResponse]] = []
        seen_urls: set[str] = set()

        for entry in self.entries:
            for result in entry.results:
                if result.url in seen_urls:
                    continue
                seen_urls.add(result.url)
                unique_sources.append((result, entry))
                if len(unique_sources) >= max_sources:
                    break
            if len(unique_sources) >= max_sources:
                break

        if not unique_sources:
            return ""

        lines = ["### Supporting Sources"]
        for result, entry in unique_sources:
            metadata = [result.provider.upper(), result.domain]
            if result.published_at:
                metadata.append(result.published_at[:10])
            lines.append(
                f"- [{result.title}]({result.url}) — {' | '.join(metadata)} — query: {entry.query}"
            )
        return "\n".join(lines)


def _get_timeout_seconds() -> float:
    raw_value = os.getenv("SEARCH_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
    try:
        return float(raw_value)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _get_result_limit() -> int:
    raw_value = os.getenv("SEARCH_NUM_RESULTS", str(DEFAULT_RESULT_LIMIT))
    try:
        value = int(raw_value)
    except ValueError:
        return DEFAULT_RESULT_LIMIT
    return max(1, min(value, 10))


def _get_max_calls_per_tool() -> int:
    raw_value = os.getenv("SEARCH_MAX_CALLS_PER_AGENT", str(DEFAULT_MAX_CALLS_PER_TOOL))
    try:
        value = int(raw_value)
    except ValueError:
        return DEFAULT_MAX_CALLS_PER_TOOL
    return max(1, value)


def _fallback_enabled() -> bool:
    return os.getenv("SEARCH_ENABLE_FALLBACK", "0").strip().lower() in {"1", "true", "yes"}


def classify_search_intent(query: str, default_intent: SearchIntent = "fast") -> SearchIntent:
    lowered = query.lower()
    if any(hint in lowered for hint in FRESHNESS_HINTS):
        return "fresh"
    return default_intent


def _configured_providers() -> list[SearchProvider]:
    providers: list[SearchProvider] = []
    if os.getenv("SERPER_API_KEY"):
        providers.append("serper")
    if os.getenv("EXA_API_KEY"):
        providers.append("exa")
    return providers


def choose_providers(intent: SearchIntent) -> list[SearchProvider]:
    configured = _configured_providers()
    if not configured:
        return []

    mode = os.getenv("SEARCH_PROVIDER_MODE", "auto").strip().lower()
    if mode in {"serper", "exa"}:
        preferred = mode
        fallbacks = [provider for provider in configured if provider != preferred]
        if preferred in configured:
            return [preferred, *fallbacks]
        return fallbacks

    if intent == "fresh":
        preferred_order: list[SearchProvider] = ["serper", "exa"]
    else:
        preferred_order = ["exa", "serper"]
    ordered = [provider for provider in preferred_order if provider in configured]
    if _fallback_enabled():
        return ordered
    return ordered[:1]


async def _search_serper(
    client: httpx.AsyncClient,
    query: str,
    *,
    num_results: int,
) -> list[SearchResult]:
    response = await client.post(
        "https://google.serper.dev/search",
        json={"q": query, "num": num_results},
        headers={"X-API-KEY": os.environ["SERPER_API_KEY"]},
    )
    response.raise_for_status()
    data = response.json()

    return [
        SearchResult(
            title=item.get("title", "").strip() or item.get("link", ""),
            url=item.get("link", ""),
            snippet=item.get("snippet", "").strip(),
            provider="serper",
            published_at=item.get("date"),
        )
        for item in data.get("organic", [])[:num_results]
        if item.get("link")
    ]


async def _search_exa(
    client: httpx.AsyncClient,
    query: str,
    *,
    num_results: int,
) -> list[SearchResult]:
    response = await client.post(
        "https://api.exa.ai/search",
        json={
            "query": query,
            "type": "fast",
            "numResults": num_results,
            "contents": {"text": {"maxCharacters": 400}},
        },
        headers={"x-api-key": os.environ["EXA_API_KEY"]},
    )
    response.raise_for_status()
    data = response.json()

    return [
        SearchResult(
            title=item.get("title", "").strip() or item.get("url", ""),
            url=item.get("url", ""),
            snippet=(item.get("text") or "").strip().replace("\n", " ")[:280],
            provider="exa",
            published_at=item.get("publishedDate"),
        )
        for item in data.get("results", [])[:num_results]
        if item.get("url")
    ]


async def routed_search(
    query: str,
    *,
    default_intent: SearchIntent = "fast",
) -> SearchResponse:
    intent = classify_search_intent(query, default_intent=default_intent)
    providers = choose_providers(intent)
    cache_key = (query.strip(), intent, os.getenv("SEARCH_PROVIDER_MODE", "auto").strip().lower())
    cached = _SEARCH_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if not providers:
        response = SearchResponse(
            query=query,
            intent=intent,
            provider=None,
            results=[],
            errors=["No search provider configured. Set SERPER_API_KEY and/or EXA_API_KEY."],
        )
        _SEARCH_CACHE[cache_key] = response
        return response

    timeout = httpx.Timeout(_get_timeout_seconds(), connect=min(_get_timeout_seconds(), 10.0))
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=timeout) as client:
        for provider in providers:
            try:
                if provider == "serper":
                    results = await _search_serper(
                        client,
                        query,
                        num_results=_get_result_limit(),
                    )
                else:
                    results = await _search_exa(
                        client,
                        query,
                        num_results=_get_result_limit(),
                    )
            except httpx.TimeoutException:
                errors.append(f"{provider}: timeout")
                continue
            except httpx.HTTPError as exc:
                errors.append(f"{provider}: {exc}")
                continue

            if results:
                response = SearchResponse(
                    query=query,
                    intent=intent,
                    provider=provider,
                    results=results,
                    errors=errors,
                )
                _SEARCH_CACHE[cache_key] = response
                return response
            errors.append(f"{provider}: no results")

    response = SearchResponse(
        query=query,
        intent=intent,
        provider=providers[0],
        results=[],
        errors=errors,
    )
    _SEARCH_CACHE[cache_key] = response
    return response


def render_search_markdown(response: SearchResponse) -> str:
    if not response.results:
        if response.errors:
            return f"[web_search error] Query: {response.query} — {'; '.join(response.errors)}"
        return f"[web_search unavailable] Query: {response.query}"

    header = (
        f"[web_search provider={response.provider} intent={response.intent} "
        f"results={len(response.results)}]"
    )
    lines = [header]
    for result in response.results:
        metadata = [result.domain]
        if result.published_at:
            metadata.append(result.published_at[:10])
        snippet = result.snippet or "No snippet available."
        lines.append(f"- {result.title} ({' | '.join(metadata)}): {snippet} [{result.url}]")
    return "\n".join(lines)


def make_web_search_tool(
    *,
    default_intent: SearchIntent,
    trace: SearchTrace | None = None,
):
    calls_used = 0

    async def web_search(query: str) -> str:
        nonlocal calls_used
        if calls_used >= _get_max_calls_per_tool():
            if trace is not None:
                trace.budget_exhausted = True
            return (
                "[web_search budget exhausted] Use the sources already gathered and "
                "only make stronger inferences from existing evidence."
            )

        calls_used += 1
        if trace is not None:
            trace.calls_used += 1
        response = await routed_search(query, default_intent=default_intent)
        if trace is not None:
            trace.record(response)
        return render_search_markdown(response)

    return web_search


def make_disabled_web_search_tool(message: str | None = None):
    disabled_message = (
        message
        or "[web_search disabled] Use the existing pipeline evidence instead of live search."
    )

    async def web_search(_: str) -> str:
        return disabled_message

    return web_search
