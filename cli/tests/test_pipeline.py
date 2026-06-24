import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from paper2product.errors import AgentExecutionError
from paper2product.models import PaperContent
from paper2product.pipeline import (
    build_compact_paper_context,
    build_full_paper_context,
    gather_agent_calls,
    _parse_quality_review,
)


class PipelineAsyncTests(unittest.IsolatedAsyncioTestCase):
    def test_compact_context_is_smaller_than_full_context(self):
        paper = PaperContent(
            paper_id="2603.09229",
            source="arxiv",
            title="Example",
            authors=["Alice", "Bob"],
            abstract="Abstract",
            full_text="Full text",
            sections={
                "introduction": "intro " * 5000,
                "method": "method " * 5000,
                "results": "results " * 5000,
            },
            figures_captions=["Figure 1"] * 20,
            tables_text=["Table 1"] * 10,
            references_titles=["Reference"] * 30,
        )
        full_context = build_full_paper_context(paper)
        compact_context = build_compact_paper_context(
            paper,
            primitives_summary="primitive summary " * 400,
        )
        self.assertLess(len(compact_context), len(full_context))
        self.assertIn("TECHNICAL PRIMITIVES SUMMARY", compact_context)

    async def test_gather_agent_calls_returns_outputs_when_all_succeed(self):
        async def ok(value: str) -> str:
            return value

        results = await gather_agent_calls(
            {
                "pain scanner": ok("pain"),
                "temporal arbitrage": ok("temporal"),
            }
        )
        self.assertEqual(results["pain scanner"], "pain")
        self.assertEqual(results["temporal arbitrage"], "temporal")

    async def test_gather_agent_calls_raises_single_controlled_error(self):
        async def ok() -> str:
            return "ok"

        async def timeout() -> str:
            raise asyncio.TimeoutError()

        with self.assertRaises(AgentExecutionError) as ctx:
            await gather_agent_calls(
                {
                    "pain scanner": ok(),
                    "temporal arbitrage": timeout(),
                }
            )

        self.assertIn("temporal arbitrage timed out inside Agentica", str(ctx.exception))

    async def test_run_pipeline_prefers_direct_backend_when_direct_key_exists(self):
        with (
            patch.dict(os.environ, {"OPENROUTER_API_KEY": "key"}, clear=True),
            patch("paper2product.pipeline.build_openai_compatible_backend", return_value="backend"),
            patch(
                "paper2product.pipeline._run_pipeline_with_openai_compatible",
                new_callable=AsyncMock,
                return_value="products_2603_09229.md",
            ) as run_direct,
            patch(
                "paper2product.pipeline._run_pipeline_with_agentica",
                new_callable=AsyncMock,
            ) as run_agentica,
        ):
            from paper2product.pipeline import run_pipeline

            output = await run_pipeline("2603.09229")

        self.assertEqual(output, "products_2603_09229.md")
        run_direct.assert_awaited_once_with(["2603.09229"], "anthropic/claude-sonnet-4", "backend", "", {})
        run_agentica.assert_not_awaited()

    def test_parse_quality_review_extracts_scores_and_flags(self):
        review = _parse_quality_review(
            """
            {
              "novelty_score": 88,
              "usefulness_score": 91,
              "evidence_score": 84,
              "duplication_risk": 12,
              "needs_revision": false,
              "issues": ["Generic buyer framing"],
              "repair_instructions": ["Name the first customer"],
              "rationale": "Strong but needs a sharper buyer."
            }
            """
        )

        self.assertEqual(review.novelty_score, 88)
        self.assertFalse(review.needs_revision)
        self.assertIn("Generic buyer framing", review.issues)
        self.assertIn("- **Novelty**: 88/100", review.as_markdown())


if __name__ == "__main__":
    unittest.main()
