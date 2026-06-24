import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from paper2product.compete import IdeaContext, parse_ideas
from paper2product.compete_tools import make_parallel_search_tool, make_tinyfish_browse_tool


SAMPLE_REPORT = """\
# 🚀 Product Ideas from: Example Paper

> **arXiv**: [2603.09229](https://arxiv.org/abs/2603.09229)
> **Generated**: 2026-03-15 12:00 UTC

---

## Executive Summary — Ranked Product Ideas

## #1: ModelGuard Enterprise
> AI model monitoring platform

### Core Insight
Non-obvious insight about why now.

### Market
TAM $5B, enterprise buyers.

---

## #2: DataFusion Labs
> Cross-domain data integration

### Core Insight
Another insight.

### Market
TAM $2B.

---

## #3: QuantumBridge
> Quantum-classical hybrid platform

### Core Insight
Third insight.

### Market
TAM $1B.

---

## Red Team Destruction

Some red team content here.
"""


class ParseIdeasTests(unittest.TestCase):
    def test_parses_all_ideas_from_report(self):
        ideas = parse_ideas(SAMPLE_REPORT)
        self.assertEqual(len(ideas), 3)
        self.assertEqual(ideas[0].rank, 1)
        self.assertEqual(ideas[0].name, "ModelGuard Enterprise")
        self.assertEqual(ideas[1].rank, 2)
        self.assertEqual(ideas[1].name, "DataFusion Labs")
        self.assertEqual(ideas[2].rank, 3)
        self.assertEqual(ideas[2].name, "QuantumBridge")

    def test_idea_content_includes_sections(self):
        ideas = parse_ideas(SAMPLE_REPORT)
        self.assertIn("Core Insight", ideas[0].content)
        self.assertIn("Market", ideas[0].content)
        self.assertIn("ModelGuard Enterprise", ideas[0].content)

    def test_idea_content_does_not_bleed_into_next(self):
        ideas = parse_ideas(SAMPLE_REPORT)
        self.assertNotIn("DataFusion", ideas[0].content)
        self.assertNotIn("QuantumBridge", ideas[1].content)

    def test_empty_report_returns_no_ideas(self):
        ideas = parse_ideas("# Some Report\n\nNo ranked ideas here.")
        self.assertEqual(len(ideas), 0)


class ParallelSearchToolTests(unittest.TestCase):
    def test_budget_enforcement(self):
        async def run_test():
            tool = make_parallel_search_tool(max_calls=1)
            with patch(
                "paper2product.compete_tools._parallel_search",
                new_callable=AsyncMock,
                return_value="[parallel_search results=3] ...",
            ):
                first = await tool("objective", "query1, query2")
                second = await tool("objective", "query3")
            self.assertIn("parallel_search", first)
            self.assertNotIn("budget", first)
            self.assertIn("budget exhausted", second)

        asyncio.run(run_test())

    def test_missing_api_key_returns_message(self):
        async def run_test():
            with patch.dict(os.environ, {}, clear=True):
                tool = make_parallel_search_tool(max_calls=1)
                result = await tool("objective", "query")
            self.assertIn("unavailable", result)

        asyncio.run(run_test())


class TinyfishBrowseToolTests(unittest.TestCase):
    def test_budget_enforcement(self):
        async def run_test():
            tool = make_tinyfish_browse_tool(max_calls=1)
            with patch(
                "paper2product.compete_tools._tinyfish_browse",
                new_callable=AsyncMock,
                return_value="[tinyfish_browse] data",
            ):
                first = await tool("https://example.com", "get pricing")
                second = await tool("https://example.com/2", "get features")
            self.assertNotIn("budget", first)
            self.assertIn("budget exhausted", second)

        asyncio.run(run_test())

    def test_missing_api_key_returns_message(self):
        async def run_test():
            with patch.dict(os.environ, {}, clear=True):
                tool = make_tinyfish_browse_tool(max_calls=1)
                result = await tool("https://example.com", "extract data")
            self.assertIn("unavailable", result)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
