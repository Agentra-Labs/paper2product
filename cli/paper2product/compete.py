"""Post-pipeline competitor intelligence agent — standalone CLI command."""

from __future__ import annotations

import asyncio
import os
import re
import sys
from rich.console import Console
console = Console()
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from dotenv import load_dotenv

from .errors import AgentExecutionError, AgenticaConnectionError
from .prompts import DEFAULT_MODEL

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PACKAGE_ROOT.parent

load_dotenv(PACKAGE_ROOT / ".env")
load_dotenv(WORKSPACE_ROOT / ".env")

IDEA_HEADER_PATTERN = re.compile(r"^## #(\d+):\s*(.+)$", re.MULTILINE)
DEFAULT_MAX_IDEAS = 3
DEFAULT_MAX_BROWSE_CALLS = 4


@dataclass
class IdeaContext:
    rank: int
    name: str
    content: str


def parse_ideas(report_md: str) -> list[IdeaContext]:
    """Parse ranked ideas from a pipeline report markdown."""
    matches = list(IDEA_HEADER_PATTERN.finditer(report_md))
    if not matches:
        return []

    ideas: list[IdeaContext] = []
    for i, match in enumerate(matches):
        rank = int(match.group(1))
        name = match.group(2).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(report_md)
        content = report_md[start:end].strip()
        ideas.append(IdeaContext(rank=rank, name=name, content=content))
    return ideas


def _get_max_ideas() -> int:
    raw = os.getenv("COMPETE_MAX_IDEAS", str(DEFAULT_MAX_IDEAS))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MAX_IDEAS


def _get_max_browse_calls() -> int:
    raw = os.getenv("COMPETE_MAX_BROWSE_CALLS", str(DEFAULT_MAX_BROWSE_CALLS))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MAX_BROWSE_CALLS


def _check_api_keys() -> None:
    """Check that at least one tool API key is configured."""
    has_parallel = bool(os.getenv("PARALLEL_API_KEY"))
    has_tinyfish = bool(os.getenv("TINYFISH_API_KEY"))
    if not has_parallel and not has_tinyfish:
        console.print(
            "[bold red]Error:[/bold red] No competitor intelligence API keys configured.\n"
            "Set PARALLEL_API_KEY and/or TINYFISH_API_KEY in your .env file.\n"
            "See cli/.env.example for details."
        )
        raise SystemExit(1)


async def _run_idea_intel_agentica(
    idea: IdeaContext,
    model: str,
    max_browse_calls: int,
) -> str:
    """Run competitor intelligence for a single idea using Agentica."""
    from .compete_prompts import COMPETITOR_INTEL_PREMISE
    from .compete_tools import make_parallel_search_tool, make_tinyfish_browse_tool
    from .pipeline import call_agent_text, spawn_agent

    agent = await spawn_agent(
        premise=COMPETITOR_INTEL_PREMISE,
        model=model,
        scope={
            "parallel_search": make_parallel_search_tool(max_calls=3),
            "tinyfish_browse": make_tinyfish_browse_tool(max_calls=max_browse_calls),
        },
    )
    return await call_agent_text(
        agent,
        f"Run competitive intelligence for this company idea:\n\n{idea.content}",
        phase=f"competitor intel: {idea.name}",
    )


async def _run_idea_intel_direct(
    idea: IdeaContext,
    model: str,
    backend,
) -> str:
    """Run competitor intelligence for a single idea using direct backend.

    Without tool use, we pre-fetch search results and pass them as context.
    """
    from .compete_prompts import COMPETITOR_INTEL_PREMISE
    from .compete_tools import _parallel_search
    from .pipeline import call_direct_text

    # Pre-fetch search context
    search_context = ""
    try:
        search_context = await _parallel_search(
            objective=f"Competitors and market landscape for: {idea.name}",
            queries=[
                f"{idea.name} competitors market",
                f"{idea.name} funding startup landscape",
            ],
        )
    except Exception:
        search_context = "[Search unavailable]"

    return await call_direct_text(
        backend,
        system_prompt=COMPETITOR_INTEL_PREMISE,
        user_prompt=(
            f"Run competitive intelligence for this company idea:\n\n{idea.content}\n\n"
            f"Pre-fetched market research:\n{search_context}\n\n"
            "Analyze the competitive landscape based on this evidence."
        ),
        phase=f"competitor intel: {idea.name}",
        model=model,
    )


async def run_compete(
    report_path: str,
    idea_indices: list[int] | None = None,
    idea_name: str | None = None,
    model: str = DEFAULT_MODEL,
) -> str:
    """Run competitor intelligence on ideas from an existing report."""
    from .backend import (
        OPENAI_COMPATIBLE_BACKEND,
        build_openai_compatible_backend,
        get_execution_backend_name,
    )

    _check_api_keys()

    report_md = Path(report_path).read_text(encoding="utf-8")
    ideas = parse_ideas(report_md)
    if not ideas:
        raise AgentExecutionError(
            f"No ranked ideas found in {report_path}. "
            "Expected headers like '## #1: Company Name'."
        )

    # Filter ideas
    if idea_name:
        ideas = [i for i in ideas if idea_name.lower() in i.name.lower()]
        if not ideas:
            raise AgentExecutionError(f"No idea matching '{idea_name}' found in report.")
    elif idea_indices:
        ideas = [i for i in ideas if i.rank in idea_indices]
        if not ideas:
            raise AgentExecutionError(
                f"No ideas with ranks {idea_indices} found in report."
            )

    max_ideas = _get_max_ideas()
    ideas = ideas[:max_ideas]
    max_browse = _get_max_browse_calls()
    backend_name = get_execution_backend_name()

    console.print(f"🔍 Running competitor intelligence on {len(ideas)} idea(s)...")
    started_at = perf_counter()

    if backend_name == OPENAI_COMPATIBLE_BACKEND:
        backend = build_openai_compatible_backend()
        tasks = {
            idea.name: _run_idea_intel_direct(idea, model, backend)
            for idea in ideas
        }
    else:
        tasks = {
            idea.name: _run_idea_intel_agentica(idea, model, max_browse)
            for idea in ideas
        }

    # Run all ideas in parallel
    names = list(tasks)
    results = await asyncio.gather(
        *(tasks[name] for name in names),
        return_exceptions=True,
    )

    intel_sections: list[str] = []
    for name, result in zip(names, results):
        if isinstance(result, BaseException):
            intel_sections.append(
                f"## Competitor Intelligence: {name}\n\n"
                f"**Error**: {result}\n"
            )
            console.print(f"  ⚠️ {name}: failed — {result}")
        else:
            intel_sections.append(result)
            console.print(f"  ✅ {name}: complete")

    elapsed = perf_counter() - started_at
    console.print(f"✅ Competitor intelligence complete in {elapsed:.1f}s")

    # Build output report
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    output = (
        f"# 🔍 Competitive Intelligence Report\n\n"
        f"> **Source**: {report_path}\n"
        f"> **Generated**: {now}\n"
        f"> **Ideas analyzed**: {len(ideas)}\n\n"
        f"---\n\n"
        + "\n\n---\n\n".join(intel_sections)
        + "\n\n---\n\n"
        "*Generated by paper2product-compete — competitive intelligence add-on*\n"
    )

    # Write output
    source_name = Path(report_path).stem
    output_path = Path(f"compete_{source_name}.md")
    output_path.write_text(output, encoding="utf-8")
    console.print(f"📄 Report saved to: {output_path}")
    return str(output_path)



