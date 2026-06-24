# Repository Guidelines

## Project Overview
**paper2product** is a multi-agent pipeline that transforms arXiv research papers into company/product opportunity reports. Python >= 3.13, managed with `uv`.

## Project Structure
- `cli/` — All code lives here. Package source at `cli/paper2product/`, tests at `cli/tests/`.
- `cli/main.py` — Thin CLI entry-point wrapper.
- `cli/pyproject.toml` — Package metadata and dependencies (no lint/typecheck config).
- `cli/agentica-docs.md` — Agentica framework reference.
- `cli/.env.example` — Environment variable template. Copy to `.env` before running.
- Generated reports (`products_*.md`), logs, and local SQLite data are **not** version-controlled.

## Build, Test, and Development Commands

All commands run from the `cli/` directory.

```bash
uv sync                                                   # install/update dependencies
uv run paper2product analyze 2603.09229                    # generate report from arXiv ID
uv run paper2product analyze "topic" --search-papers       # topic discovery (needs ENABLE_PAPER_SEARCH=1)
uv run paper2product analyze --idea "startup idea" --search-papers  # idea-driven paper search
uv run paper2product serve                                 # start FastAPI service on port 8010
uv run paper2product-compete report.md --ideas 1,2         # competitor intel on report ideas
uv run paper2product init                                  # interactive API key setup

# Testing
uv run python -m unittest discover -s tests                        # run full test suite
uv run python -m unittest tests.test_pipeline                      # run single test module
uv run python -m unittest tests.test_pipeline.PipelineAsyncTests   # run single test class
uv run python -m unittest tests.test_pipeline.PipelineAsyncTests.test_parse_quality_review_extracts_scores_and_flags  # run single test
```

There is **no linter or type-checker configured** in this project. Use standard Python conventions and manual review.

## Coding Style & Naming Conventions

### Formatting
- 4-space indentation throughout.
- Keep lines under ~100 characters where practical; no hard limit enforced.
- Use `from __future__ import annotations` when forward references or `X | Y` type unions appear in older Python contexts.

### Imports
- Standard library first, then third-party, then local relative imports (separated by blank lines).
- Import specific names rather than entire modules where possible (e.g., `from .errors import AgentExecutionError`).
- Avoid circular imports; use lazy/deferred imports inside functions when necessary (see `pipeline.py` for examples).

### Types
- Type hints required on all **public** functions and methods.
- Use modern union syntax: `str | None` instead of `Optional[str]` (Python 3.10+).
- Use `typing.Any`, `typing.Literal`, and `collections.abc.Awaitable` where appropriate.
- Dataclasses are preferred over plain dicts for structured data (`@dataclass` with `slots=True` on performance-sensitive types).

### Naming
- `snake_case` for functions, methods, and variables.
- `UPPER_SNAKE_CASE` for module-level constants and prompt string constants (`DECOMPOSER_PREMISE`, `DEFAULT_MODEL`).
- `PascalCase` for classes and exception types.
- Private helpers prefixed with underscore (`_truncate_text`, `_get_speed_profile`).
- Test classes named `*Tests` (e.g., `PipelineAsyncTests`, `BackendSelectionTests`).
- Test files named `test_<feature>.py`.

### Error Handling
- Custom exceptions live in `errors.py`: `AgentExecutionError` (execution failures/timeouts) and `AgenticaConnectionError` (network/connectivity).
- Use `raise ... from exc` chaining for re-raised exceptions.
- Wrap external calls with `asyncio.wait_for` timeouts; provide descriptive error messages.
- Graceful degradation: prefer fallback behavior over crashing (e.g., `_load_learning_digest` returns empty string on failure).

### Async Patterns
- Pipeline orchestration uses `asyncio` throughout.
- Use `asyncio.gather` with `return_exceptions=True` for parallel agent calls; check results for exceptions before using.
- Agent teardown: always attempt `await agent.close()` in `finally` blocks (best-effort, shielded with timeout).
- HTTP calls use `httpx.AsyncClient` with explicit timeouts.

## Agentica Framework
Reference docs: `cli/agentica-docs.md`. Core pattern:
```python
agent = await spawn(premise=PREMISE_CONSTANT, model=model, scope={"web_search": tool})
result = await agent.call(str, prompt)
```
Model names must be valid OpenRouter slugs (e.g., `anthropic/claude-sonnet-4`).

## Testing Guidelines
- Tests use Python's built-in `unittest` framework with `unittest.IsolatedAsyncioTestCase` for async tests.
- Use `unittest.mock.patch` / `patch.dict` for environment and network mocking.
- Tests should **not** make real network or API calls; mock external services.
- Each test file covers one feature area and imports from `paper2product.*` directly.

## Commit & PR Guidelines
- Short imperative commit subjects (e.g., "add quality review pipeline", "fix timeout handling").
- One concern per commit.
- Do not commit `.env` files, API keys, generated reports, or `data/` contents.

## Configuration
- Environment variables are loaded from `.env` (see `.env.example` for all options).
- Key variables: `AGENTICA_API_KEY` or `OPENROUTER_API_KEY` (execution), `SERPER_API_KEY` / `EXA_API_KEY` (search), `PIPELINE_SPEED_PROFILE` (balanced/exhaustive).
- Do not add Python package-manager metadata at the repo root — keep everything under `cli/`.

## Key Modules

| Module | Purpose |
|---|---|
| `pipeline.py` | Core 5-phase pipeline orchestrator (Decomposer → Pain Scanner → Infra Inversion → Temporal → Red Team → Synthesizer + Quality Review) |
| `prompts.py` | All agent premises as `UPPER_SNAKE_CASE` constants |
| `backend.py` | Execution backend abstraction (Agentica vs OpenAI-compatible) |
| `research.py` | Web search (Serper/Exa) with budget enforcement and intent routing |
| `paper_search.py` | PASA-style topic discovery (Crawler + Selector agents) |
| `compete.py` | Post-pipeline competitor intelligence CLI |
| `compete_tools.py` | Parallel.ai search + Tinyfish browse tools |
| `ingestion.py` | arXiv PDF fetching and section extraction |
| `models.py` | Core data models (`PaperContent` dataclass) |
| `errors.py` | Custom exception types |
| `reporting.py` | Markdown report generation |
| `service.py` / `service_store.py` | FastAPI service + SQLite persistence |
