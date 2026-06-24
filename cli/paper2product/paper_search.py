"""PASA-inspired paper search agent — Crawler + Selector for topic-based discovery."""

from __future__ import annotations

import asyncio
import json
import os
import re
from rich.console import Console
console = Console()
from dataclasses import dataclass
from time import perf_counter

import arxiv
import httpx

from .backend import (
    AGENTICA_BACKEND,
    APODEX_BACKEND,
    OPENAI_COMPATIBLE_BACKEND,
    OpenAICompatibleBackend,
    build_openai_compatible_backend,
    get_execution_backend_name,
)
from .errors import AgentExecutionError
from .prompts import (
    DEFAULT_MODEL,
    PAPER_CRAWLER_PREMISE,
    PAPER_SELECTOR_PREMISE,
)
from .research import SearchTrace, make_web_search_tool
from .sources import fetch_paper

ARXIV_ID_PATTERN = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
ARXIV_URL_PATTERN = re.compile(
    r"^https?://(www\.)?(arxiv\.org|alphaxiv\.org)/(abs|pdf)/"
)
PAPER_SEARCH_MAX_RESULTS = 10
PAPER_SEARCH_TIMEOUT_SECONDS = 60.0


@dataclass
class PaperSearchResult:
    arxiv_id: str
    title: str
    abstract: str
    score: float
    reason: str
    github_url: str = ""


def is_topic_query(input_str: str) -> bool:
    """Return True if input is a free-text topic, not an arXiv ID or URL."""
    stripped = input_str.strip()
    if ARXIV_ID_PATTERN.match(stripped):
        return False
    if ARXIV_URL_PATTERN.match(stripped):
        return False
    return True


def _paper_search_enabled() -> bool:
    return os.getenv("ENABLE_PAPER_SEARCH", "0").strip().lower() in {"1", "true", "yes"}


async def _arxiv_search(query: str, max_results: int = PAPER_SEARCH_MAX_RESULTS) -> str:
    """Search arXiv and return formatted results with title, abstract, and ID."""
    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )
    results: list[str] = []
    for paper in client.results(search):
        arxiv_id = paper.entry_id.split("/abs/")[-1].split("v")[0]
        abstract = paper.summary.replace("\n", " ")
        abstract_short = abstract[:400]
        
        # Heuristic for github links in abstract
        github_match = re.search(r"https?://github\.com/[a-zA-Z0-9\-_./]+", abstract)
        github_info = f"\n  GitHub: {github_match.group(0)}" if github_match else ""
        
        results.append(f"- [{arxiv_id}] {paper.title}{github_info}\n  Abstract: {abstract_short}")
    if not results:
        return f"[arxiv_search] No results for: {query}"
    return f"[arxiv_search results={len(results)}]\n" + "\n".join(results)


async def _semantic_scholar_search(query: str, max_results: int = 10) -> str:
    """Search Semantic Scholar API and return formatted results."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={
                    "query": query,
                    "limit": max_results,
                    "fields": "title,abstract,paperId,year,authors",
                },
            )
            if response.status_code != 200:
                return f"[semantic_scholar] API error: {response.status_code}"
            data = response.json()
            papers = data.get("data", [])
            if not papers:
                return f"[semantic_scholar] No results for: {query}"
            results = []
            for paper in papers:
                paper_id = paper.get("paperId", "")
                # Try to get arXiv ID if available
                arxiv_id = ""
                if "arxiv" in paper_id.lower():
                    arxiv_id = paper_id.split(":")[-1] if ":" in paper_id else paper_id
                title = paper.get("title", "Untitled")
                abstract = paper.get("abstract") or "No abstract available"
                abstract_clean = abstract.replace("\n", " ")
                abstract_short = abstract_clean[:400]
                
                # Heuristic for github links in abstract
                github_match = re.search(r"https?://github\.com/[a-zA-Z0-9\-_./]+", abstract_clean)
                github_info = f"\n  GitHub: {github_match.group(0)}" if github_match else ""
                
                year = paper.get("year", "")
                prefix = f"[{arxiv_id}]" if arxiv_id else f"[ss:{paper_id[:8]}]"
                results.append(
                    f"- {prefix} {title} ({year}){github_info}\n  Abstract: {abstract_short}"
                )
            return f"[semantic_scholar results={len(results)}]\n" + "\n".join(results)
    except Exception as e:
        return f"[semantic_scholar] Error: {str(e)[:100]}"


async def _combined_paper_search(query: str, max_results: int = 10) -> str:
    """Run arXiv and Semantic Scholar searches in parallel, combine results."""
    arxiv_results, ss_results = await asyncio.gather(
        _arxiv_search(query, max_results),
        _semantic_scholar_search(query, max_results),
        return_exceptions=True,
    )
    if isinstance(arxiv_results, Exception):
        arxiv_results = f"[arxiv_search] Error: {str(arxiv_results)[:100]}"
    if isinstance(ss_results, Exception):
        ss_results = f"[semantic_scholar] Error: {str(ss_results)[:100]}"
    return f"{arxiv_results}\n\n{ss_results}"


def _make_arxiv_search_tool():
    """Create an arxiv search tool callable for agent scope."""

    async def arxiv_search_tool(query: str) -> str:
        return await _combined_paper_search(query)

    return arxiv_search_tool


def _parse_selector_output(text: str) -> list[PaperSearchResult]:
    """Parse the Selector agent's JSON output into PaperSearchResult list."""
    # Try to extract JSON array from the response
    text = text.strip()
    # Handle markdown code blocks
    if "```" in text:
        match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if match:
            text = match.group(1)
    # Find the JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        items = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []

    results: list[PaperSearchResult] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        arxiv_id = item.get("arxiv_id", "")
        if not arxiv_id:
            continue
        results.append(
            PaperSearchResult(
                arxiv_id=str(arxiv_id),
                title=str(item.get("title", "")),
                abstract=str(item.get("abstract", "")),
                score=float(item.get("score", 0.0)),
                reason=str(item.get("reason", "")),
                github_url=str(item.get("github_url", "")),
            )
        )
    results.sort(key=lambda r: r.score, reverse=True)
    github_results = [result for result in results if result.github_url]
    return github_results or results


async def _run_paper_search_agentica(
    topic: str,
    model: str,
) -> list[PaperSearchResult]:
    """Run paper search using Agentica backend."""
    import asyncio

    from agentica import spawn

    from .pipeline import call_agent_text, spawn_agent

    search_trace = SearchTrace(section_name="Paper Discovery")

    # Phase 0a: Crawler
    crawler = await spawn_agent(
        premise=PAPER_CRAWLER_PREMISE,
        model=model,
        scope={
            "web_search": make_web_search_tool(
                default_intent="fresh",
                trace=search_trace,
            ),
            "arxiv_search": _make_arxiv_search_tool(),
        },
    )
    crawler_output = await call_agent_text(
        crawler,
        f"Find the most relevant research papers for this topic:\n\n{topic}\n\n"
        "Use arxiv_search and web_search to build a comprehensive candidate list. "
        "Follow key citations when you find highly relevant papers.",
        phase="paper search: crawling",
    )

    # Phase 0b: Selector — score and rank
    selector = await spawn_agent(
        premise=PAPER_SELECTOR_PREMISE,
        model=model,
    )

    # Enrich crawler output with abstracts from arXiv
    enrichment = await _enrich_candidates(crawler_output)

    selector_output = await call_agent_text(
        selector,
        f"Topic: {topic}\n\n"
        f"Candidate papers from crawler:\n{crawler_output}\n\n"
        f"Additional abstracts:\n{enrichment}\n\n"
        "Score and rank these papers. Return the top 3-5 as a JSON array.",
        phase="paper search: selection",
    )
    return _parse_selector_output(selector_output)


async def _run_paper_search_direct(
    topic: str,
    model: str,
    backend: OpenAICompatibleBackend,
) -> list[PaperSearchResult]:
    """Run paper search using OpenAI-compatible backend (no tool use, simpler)."""
    from .pipeline import call_direct_text

    # Do an arXiv search ourselves and feed results to the LLM for ranking
    search_results = await _combined_paper_search(topic)

    selector_output = await call_direct_text(
        backend,
        system_prompt=PAPER_SELECTOR_PREMISE,
        user_prompt=(
            f"Topic: {topic}\n\n"
            f"Candidate papers:\n{search_results}\n\n"
            "Score and rank these papers. Return the top 3-5 as a JSON array."
        ),
        phase="paper search: selection",
        model=model,
    )
    return _parse_selector_output(selector_output)


async def _enrich_candidates(crawler_output: str) -> str:
    """Extract arXiv IDs from crawler output and fetch their abstracts."""
    ids = re.findall(r"\b(\d{4}\.\d{4,5})\b", crawler_output)
    if not ids:
        return ""
    unique_ids = list(dict.fromkeys(ids))[:10]

    client = arxiv.Client()
    search = arxiv.Search(id_list=unique_ids)
    lines: list[str] = []
    for paper in client.results(search):
        arxiv_id = paper.entry_id.split("/abs/")[-1].split("v")[0]
        abstract = paper.summary.replace("\n", " ")
        abstract_short = abstract[:500]
        
        # Heuristic for github links
        github_match = re.search(r"https?://github\.com/[a-zA-Z0-9\-_./]+", abstract)
        github_info = f"\n  GitHub: {github_match.group(0)}" if github_match else ""
        
        lines.append(f"### [{arxiv_id}] {paper.title}{github_info}\n{abstract_short}")
    return "\n\n".join(lines)


async def _run_paper_search_apodex(topic: str) -> list[PaperSearchResult]:
    """Run paper search using Apodex deep research backend.

    Apodex has built-in web search, so we ask it directly to find and rank papers.
    We also do our own arXiv + Semantic Scholar search and feed those as candidates.
    """
    from .apodex import build_apodex_backend, get_apodex_phase_model
    from .pipeline import call_apodex_text

    backend = build_apodex_backend()

    # Gather candidates from our own APIs
    search_results = await _combined_paper_search(topic)

    selector_output = await call_apodex_text(
        backend,
        system_prompt=PAPER_SELECTOR_PREMISE,
        user_prompt=(
            f"Topic: {topic}\n\n"
            f"Candidate papers from arXiv and Semantic Scholar:\n{search_results}\n\n"
            "Score and rank these papers. Search the web to find any additional "
            "recent papers with GitHub code that we may have missed. "
            "Return the top 3-5 as a JSON array."
        ),
        phase="paper search: selection",
    )
    return _parse_selector_output(selector_output)


async def run_paper_search(
    topic: str,
    model: str = DEFAULT_MODEL,
) -> list[PaperSearchResult]:
    """Run the PASA-style paper search pipeline. Returns ranked papers."""
    started_at = perf_counter()
    console.print(f"🔍 Paper search: discovering papers for topic: {topic}")

    backend_name = get_execution_backend_name()
    if backend_name == APODEX_BACKEND:
        results = await _run_paper_search_apodex(topic)
    elif backend_name == OPENAI_COMPATIBLE_BACKEND:
        backend = build_openai_compatible_backend()
        results = await _run_paper_search_direct(topic, model, backend)
    else:
        results = await _run_paper_search_agentica(topic, model)

    elapsed = perf_counter() - started_at
    console.print(f"  ✅ Paper search complete in {elapsed:.1f}s — found {len(results)} papers")
    for i, r in enumerate(results, 1):
        console.print(f"     {i}. [{r.arxiv_id}] {r.title} (score={r.score:.2f})")

    return results
