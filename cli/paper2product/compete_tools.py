"""Tools for the competitor intelligence agent — Parallel.ai search + Tinyfish browse."""

from __future__ import annotations

import os
from typing import Callable

import httpx

from .errors import AgentExecutionError

DEFAULT_PARALLEL_TIMEOUT = 20.0
DEFAULT_TINYFISH_TIMEOUT = 45.0


async def _parallel_search(
    objective: str,
    queries: list[str],
    *,
    max_results: int = 5,
    max_chars_per_result: int = 600,
) -> str:
    """Call Parallel.ai Search API and return formatted markdown."""
    api_key = os.getenv("PARALLEL_API_KEY", "")
    if not api_key:
        return "[parallel_search unavailable] PARALLEL_API_KEY not configured."

    timeout = httpx.Timeout(DEFAULT_PARALLEL_TIMEOUT, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            "https://api.parallel.ai/v1beta/search",
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
            },
            json={
                "objective": objective,
                "search_queries": queries[:4],
                "mode": "fast",
                "max_results": max_results,
                "excerpts": {"max_chars_per_result": max_chars_per_result},
            },
        )
        response.raise_for_status()
        data = response.json()

    results = data.get("results", [])
    if not results:
        return f"[parallel_search] No results for: {objective}"

    lines = [f"[parallel_search results={len(results)}]"]
    for item in results:
        title = item.get("title", "Untitled")
        url = item.get("url", "")
        excerpts = item.get("excerpts", [])
        snippet = excerpts[0][:400] if excerpts else "No excerpt."
        lines.append(f"- {title} ({url}): {snippet}")
    return "\n".join(lines)


async def _tinyfish_browse(url: str, goal: str) -> str:
    """Call Tinyfish SSE endpoint to browse a URL with a specific goal."""
    api_key = os.getenv("TINYFISH_API_KEY", "")
    if not api_key:
        return "[tinyfish_browse unavailable] TINYFISH_API_KEY not configured."

    timeout = httpx.Timeout(DEFAULT_TINYFISH_TIMEOUT, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            "https://agent.tinyfish.ai/v1/automation/run-sse",
            headers={
                "X-API-Key": api_key,
                "Content-Type": "application/json",
            },
            json={"url": url, "goal": goal},
        ) as response:
            response.raise_for_status()
            result_text = ""
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if '"type":"COMPLETE"' in payload or '"status":"COMPLETED"' in payload:
                    # Try to extract resultJson
                    import json

                    try:
                        event = json.loads(payload)
                        result_json = event.get("resultJson")
                        if result_json:
                            if isinstance(result_json, dict):
                                result_text = json.dumps(result_json, indent=2)
                            else:
                                result_text = str(result_json)
                        elif event.get("result"):
                            result_text = str(event["result"])
                    except json.JSONDecodeError:
                        result_text = payload
                    break
                elif '"type":"ERROR"' in payload:
                    return f"[tinyfish_browse error] {payload[:400]}"

    if not result_text:
        return f"[tinyfish_browse] No result from: {url}"
    return f"[tinyfish_browse url={url}]\n{result_text[:2000]}"


def make_parallel_search_tool(max_calls: int = 3) -> Callable:
    """Create a budget-limited parallel search tool for agent scope."""
    calls_used = 0

    async def parallel_search(objective: str, queries: str = "") -> str:
        """Search the web for competitive intelligence. Provide an objective and
        comma-separated search queries."""
        nonlocal calls_used
        if calls_used >= max_calls:
            return "[parallel_search budget exhausted] Use existing evidence."
        calls_used += 1
        query_list = [q.strip() for q in queries.split(",") if q.strip()] if queries else []
        if not query_list:
            query_list = [objective]
        try:
            return await _parallel_search(objective, query_list)
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            return f"[parallel_search error] {exc}"

    return parallel_search


def make_tinyfish_browse_tool(max_calls: int = 4) -> Callable:
    """Create a budget-limited Tinyfish browse tool for agent scope."""
    calls_used = 0

    async def tinyfish_browse(url: str, goal: str = "") -> str:
        """Browse a specific URL to extract structured data. Provide the URL
        and a goal describing what to extract."""
        nonlocal calls_used
        if calls_used >= max_calls:
            return "[tinyfish_browse budget exhausted] Use existing evidence."
        calls_used += 1
        if not goal:
            goal = "Extract key information from this page."
        try:
            return await _tinyfish_browse(url, goal)
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            return f"[tinyfish_browse error] {exc}"

    return tinyfish_browse
