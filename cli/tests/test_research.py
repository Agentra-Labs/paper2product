import os
import unittest
from unittest.mock import patch

from paper2product.research import (
    SearchResponse,
    SearchResult,
    SearchTrace,
    choose_providers,
    classify_search_intent,
    make_web_search_tool,
    render_search_markdown,
)


class SearchRoutingTests(unittest.TestCase):
    def test_classify_search_intent_prefers_fresh_for_current_fact_queries(self):
        intent = classify_search_intent(
            "latest AI startup funding and current competitors",
            default_intent="fast",
        )
        self.assertEqual(intent, "fresh")

    def test_choose_providers_prefers_exa_for_fast_queries(self):
        with patch.dict(
            os.environ,
            {
                "SERPER_API_KEY": "serper-key",
                "EXA_API_KEY": "exa-key",
                "SEARCH_PROVIDER_MODE": "auto",
                "SEARCH_ENABLE_FALLBACK": "0",
            },
            clear=False,
        ):
            self.assertEqual(choose_providers("fast"), ["exa"])
            self.assertEqual(choose_providers("fresh"), ["serper"])

    def test_choose_providers_returns_fallback_chain_when_enabled(self):
        with patch.dict(
            os.environ,
            {
                "SERPER_API_KEY": "serper-key",
                "EXA_API_KEY": "exa-key",
                "SEARCH_PROVIDER_MODE": "auto",
                "SEARCH_ENABLE_FALLBACK": "1",
            },
            clear=False,
        ):
            self.assertEqual(choose_providers("fast"), ["exa", "serper"])
            self.assertEqual(choose_providers("fresh"), ["serper", "exa"])

    def test_render_search_markdown_includes_provider_and_url(self):
        response = SearchResponse(
            query="current AI news",
            intent="fresh",
            provider="serper",
            results=[
                SearchResult(
                    title="AI market update",
                    url="https://example.com/report",
                    snippet="A concise snippet",
                    provider="serper",
                    published_at="2026-03-01T00:00:00Z",
                )
            ],
        )
        rendered = render_search_markdown(response)
        self.assertIn("provider=serper", rendered)
        self.assertIn("https://example.com/report", rendered)

    def test_trace_render_markdown_deduplicates_urls(self):
        trace = SearchTrace(section_name="Market Pain Mapping")
        result = SearchResult(
            title="Example report",
            url="https://example.com/report",
            snippet="Snippet",
            provider="exa",
            published_at="2026-03-01T00:00:00Z",
        )
        response = SearchResponse(
            query="market report",
            intent="fast",
            provider="exa",
            results=[result],
        )
        trace.record(response)
        trace.record(response)
        rendered = trace.render_markdown()
        self.assertEqual(rendered.count("https://example.com/report"), 1)

    def test_web_search_tool_enforces_budget(self):
        async def run_test():
            with patch.dict(
                os.environ,
                {
                    "SEARCH_MAX_CALLS_PER_AGENT": "1",
                },
                clear=False,
            ):
                tool = make_web_search_tool(default_intent="fast")
                first = await tool("query one")
                second = await tool("query two")
                self.assertIn("[web_search", first)
                self.assertIn("budget exhausted", second)

        import asyncio

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
