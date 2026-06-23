# paper2product

Transforms research papers into fresh/new company/product opportunity reports using a multi-agent AI pipeline.

## What It Does

The pipeline analyzes a research paper through 5 adversarial phases:

1. **Decomposer** — Extracts atomic technical primitives (building blocks, not just "key ideas")
2. **Pain Scanner** — Maps primitives to real market pain via web research
3. **Infrastructure Inversion** — Finds second-order problems that adoption creates
4. **Temporal Arbitrage** — Identifies time-limited build opportunities
5. **Red Team Destroyer** — Brutally attacks every idea; only survivors make the cut

Output: A ranked list of 4-6 company ideas with market analysis, moats, and first-90-days plans.

---

## Setup

```bash
cd cli
uv sync
uv run arxiv2product init   # interactive setup for API keys
```

The `init` command will prompt you for required keys and save them to `~/.arxiv2product/.env`.

**Required keys:**
- `AGENTICA_API_KEY` (default backend) — or use OpenRouter with `OPENROUTER_API_KEY`
- `SERPER_API_KEY` and/or `EXA_API_KEY` — for web search during pipeline phases

---

## Usage

### Basic: Generate a Report

```bash
cd cli

# From an arXiv ID
uv run arxiv2product analyze 2603.09229

# Render in terminal (Uses glow if available, falls back to Rich)
uv run arxiv2product analyze 2603.09229 --display

# Automatically open the report when finished
uv run arxiv2product analyze 2603.09229 --open
```

Output: `products_2603_09229.md` — a markdown report with ranked company ideas.

### Topic Discovery Mode (PASA-style)

**When you don't have a specific paper yet.** Instead of an arXiv ID, pass a research topic:

```bash
# Enable topic discovery in .env or via environment variable
ENABLE_PAPER_SEARCH=1 uv run arxiv2product analyze "self-adapting language models" --search-papers
```

The pipeline will:
1. Run a PASA-style Crawler agent to find relevant papers (arXiv + web search)
2. Run a Selector agent to score and rank them
3. Pick the top papers and run the full 5-phase analysis

### Bring Your Own Idea (Validation & Augmentation)

**When you already have a startup idea.** You can invert the pipeline to structurally validate and augment your specific idea using research papers.

```bash
# Validate your idea against a specific paper
uv run arxiv2product analyze 2603.09229 --idea "A developer tool that automates PR reviews"

# Have the pipeline find the top 5 relevant papers to validate your idea
uv run arxiv2product analyze --idea "A startup building AI-designed metamaterials" --search-papers
```

When you provide an `--idea`, the pipeline's agents (Cross-pollinator, Infrastructure Inversion, Temporal Arbitrage, and Destroyer) will anchor their analysis entirely on your concept—acting as a technical simulation lab to build out the architecture and find its mechanical failure points.

---

### Competitor Intelligence Add-on

**When you have a report you care about.** Run deep competitive analysis on specific ideas:

```bash
# After generating a report, analyze its top ideas
uv run arxiv2product compete products_2603_09229.md

# Analyze only specific ideas by rank
uv run arxiv2product compete products_2603_09229.md --ideas 1,2

# Analyze a specific idea by name
uv run arxiv2product compete products_2603_09229.md --idea "ModelGuard"
```

**Required keys:**
- `PARALLEL_API_KEY` — Parallel.ai search (broad web research)
- `TINYFISH_API_KEY` — Tinyfish browser automation (deep site crawling)

---

## API Service

Run as a local FastAPI service:

```bash
cd cli
uv run arxiv2product serve
# Runs on http://127.0.0.1:8010
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/dashboard/{userId}` | User's report history |
| `POST` | `/reports` | Create a report job (async) |
| `GET` | `/reports/{jobId}` | Poll report status/result |
| `POST` | `/feedback/score` | Submit feedback on a report |

---

## Configuration

The CLI looks for `.env` in this order:
1. Current working directory: `./.env`
2. `./cli/.env`
3. Project root (parent of cli): `../.env`
4. `~/.arxiv2product/.env` (recommended for uv tool installations)

Use `uv run arxiv2product init` to easily configure your environment.

---

## Tests

```bash
cd cli
uv run python -m unittest discover -s tests
```

---

## Repository Layout

```
.
├── README.md
├── GEMINI.md              # Contextual guide for AI assistants
├── cli/
│   ├── .env.example       # Environment variable reference
│   ├── pyproject.toml     # Package definition (cli2 + rich)
│   ├── agentica-docs.md   # Agentica framework reference
│   ├── main.py            # CLI entry point wrapper
│   ├── arxiv2product/     # Package source
│   │   ├── cli.py         # Unified CLI (analyze, compete, serve, init)
│   │   ├── pipeline.py    # Core 5-phase pipeline (Rich output)
│   │   ├── prompts.py     # Agent premises/prompts
│   │   ├── paper_search.py    # PASA-style topic discovery
│   │   ├── compete.py     # Competitor intel logic
│   │   └── ...
│   └── tests/             # Test suite
```

---

## When to Use What

| Goal | Command | Notes |
|------|---------|-------|
| Setup environment | `arxiv2product init` | Interactive API key config |
| Analyze a specific paper | `arxiv2product analyze 2603.09229` | Standard 5-phase pipeline |
| Explore a research area | `arxiv2product analyze "topic" --search-papers` | Finds best paper, then analyzes |
| Deep-dive on an idea | `arxiv2product compete report.md` | Post-pipeline competitive intel |
| Run as a service | `arxiv2product serve` | FastAPI on port 8010 |

---

## License

MIT
