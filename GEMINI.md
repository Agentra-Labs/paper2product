# GEMINI.md

## Project Overview
**paper2product** is a multi-agent AI pipeline designed to transform arXiv research papers into comprehensive company and product opportunity reports. It employs a sophisticated, 5-phase adversarial process to analyze technical primitives and map them to market needs, infrastructure gaps, and temporal opportunities.

### Core Architecture (5-Phase Pipeline)
1.  **Decomposer:** Extracts atomic technical primitives and building blocks from the paper.
2.  **Pain Scanner:** Maps primitives to real-world market pain points using web research.
3.  **Infrastructure Inversion:** Identifies second-order problems created by the adoption of the technology.
4.  **Temporal Arbitrage:** Finds time-limited opportunities for building.
5.  **Red Team Destroyer:** Critically evaluates every idea, ensuring only the most robust survive.
*Final Synthesis:* A ranked list of 4-6 company ideas with market analysis and execution plans.

### Key Technologies
- **Language:** Python (>= 3.13)
- **Dependency Management:** `uv`
- **Frameworks:** `symbolica-agentica` (Agent orchestration), `FastAPI` (Service), `Click` (CLI)
- **APIs:** arXiv (PDF ingestion), Serper/Exa (Search), Parallel/Tinyfish (Competitor intel)
- **Utilities:** `pdfplumber`, `pydantic`, `python-dotenv`

---

## Building and Running

### Setup
Ensure you have `uv` installed, then run:
```bash
cd cli
uv sync
cp .env.example .env # Configure your API keys (AGENTICA_API_KEY, etc.)
```

### CLI Commands
- **Generate Report:** `uv run paper2product analyze <arxiv_id_or_url>`
- **Display Report:** `uv run paper2product analyze <id> --display` (Uses `glow` if installed, falls back to `rich`)
- **Topic Discovery:** `uv run paper2product analyze "research topic" --search-papers`
- **Competitor Intelligence:** `uv run paper2product compete <report_path>.md`
- **Start API Service:** `uv run paper2product serve` (Default port: 8010)
- **Interactive Setup:** `uv run paper2product init` (Configure API keys interactively)

### Testing
Run the test suite using `unittest`:
```bash
cd cli
uv run python -m unittest discover -s tests
```

---

## Development Conventions

### Coding Style
- **Indentation:** 4-space indentation.
- **Type Hints:** Required for all public-facing functions and methods.
- **Naming:** `snake_case` for variables and functions; `UPPER_SNAKE_CASE` for prompt constants and environment variables.
- **Orchestration:** Use `asyncio` for all agentic and network-bound orchestration.

### Directory Structure
- `cli/paper2product/`: Core package logic.
- `cli/tests/`: Unit and integration tests.
- `cli/main.py`: Main CLI entry point wrapper.
- `cli/agentica-docs.md`: Reference for the Agentica framework used in this project.
- `AGENTS.md`: Specific behavioral and structural mandates for AI assistants working in this repo.

---

## Roadmap & Future Directions
- **FastMCP Integration**: Implement a Model Context Protocol server using `FastMCP` to allow any AI agent (Cursor, Windsurf, Claude Desktop) to use the 5-phase pipeline as a set of standardized tools.
- **Dynamic Resource Provisioning**: Expose generated reports and extracted technical primitives as MCP Resources for RAG-based agent reasoning.
- **Advanced Code Skimming**: Deepen the GitHub integration to perform automated AST-based analysis of repository sections during the Decomposer phase.

### Agent Configuration
- **Prompts:** Centralized in `cli/paper2product/prompts.py` as `UPPER_SNAKE_CASE` constants.
- **Execution:** Uses the `spawn` + `agent.call` pattern from `agentica`.
- **Backends:** Supports both `agentica` and `openai_compatible` (e.g., OpenRouter) via `backend.py`.

### Environment Configuration
The project looks for `.env` files in multiple locations, prioritizing the current working directory. Key variables include:
- `AGENTICA_API_KEY`: Required for the default backend.
- `ENABLE_PAPER_SEARCH`: Toggle for topic-to-paper discovery mode.
- `PIPELINE_SPEED_PROFILE`: `balanced` or `exhaustive` tuning.
