import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from paper2product.paper_search import (
    PaperSearchResult,
    _parse_selector_output,
    is_topic_query,
)


class TopicDetectionTests(unittest.TestCase):
    def test_arxiv_id_is_not_topic(self):
        self.assertFalse(is_topic_query("2603.09229"))
        self.assertFalse(is_topic_query("2501.10120"))

    def test_arxiv_id_with_version_is_not_topic(self):
        self.assertFalse(is_topic_query("2603.09229v2"))

    def test_arxiv_url_is_not_topic(self):
        self.assertFalse(is_topic_query("https://arxiv.org/abs/2603.09229"))
        self.assertFalse(is_topic_query("https://alphaxiv.org/abs/2603.09229"))

    def test_free_text_is_topic(self):
        self.assertTrue(is_topic_query("self-adapting language models"))
        self.assertTrue(is_topic_query("quantum error correction"))
        self.assertTrue(is_topic_query("protein folding transformers"))

    def test_whitespace_handling(self):
        self.assertFalse(is_topic_query("  2603.09229  "))
        self.assertTrue(is_topic_query("  deep learning optimization  "))


class SelectorParsingTests(unittest.TestCase):
    def test_parse_valid_json_array(self):
        text = json.dumps([
            {
                "arxiv_id": "2603.09229",
                "title": "Example Paper",
                "abstract": "An abstract.",
                "score": 0.95,
                "reason": "Highly relevant.",
            },
            {
                "arxiv_id": "2501.10120",
                "title": "Another Paper",
                "abstract": "Another abstract.",
                "score": 0.80,
                "reason": "Somewhat relevant.",
            },
        ])
        results = _parse_selector_output(text)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].arxiv_id, "2603.09229")
        self.assertAlmostEqual(results[0].score, 0.95)
        self.assertEqual(results[1].arxiv_id, "2501.10120")

    def test_parse_json_in_code_block(self):
        text = '```json\n[{"arxiv_id": "2603.09229", "title": "T", "abstract": "A", "score": 0.9, "reason": "R"}]\n```'
        results = _parse_selector_output(text)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].arxiv_id, "2603.09229")

    def test_parse_empty_response(self):
        self.assertEqual(_parse_selector_output(""), [])
        self.assertEqual(_parse_selector_output("No results found."), [])

    def test_parse_sorts_by_score_descending(self):
        text = json.dumps([
            {"arxiv_id": "low", "title": "", "abstract": "", "score": 0.5, "reason": ""},
            {"arxiv_id": "high", "title": "", "abstract": "", "score": 0.9, "reason": ""},
        ])
        results = _parse_selector_output(text)
        self.assertEqual(results[0].arxiv_id, "high")
        self.assertEqual(results[1].arxiv_id, "low")

    def test_parse_skips_entries_without_arxiv_id(self):
        text = json.dumps([
            {"title": "No ID", "abstract": "", "score": 0.9, "reason": ""},
            {"arxiv_id": "2603.09229", "title": "Has ID", "abstract": "", "score": 0.8, "reason": ""},
        ])
        results = _parse_selector_output(text)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].arxiv_id, "2603.09229")

    def test_parse_prefers_github_linked_entries(self):
        text = json.dumps([
            {
                "arxiv_id": "2603.00001",
                "title": "No Repo",
                "abstract": "",
                "score": 0.95,
                "reason": "Missing repo",
                "github_url": "",
            },
            {
                "arxiv_id": "2603.00002",
                "title": "Has Repo",
                "abstract": "",
                "score": 0.90,
                "reason": "Has code",
                "github_url": "https://github.com/example/repo",
            },
        ])
        results = _parse_selector_output(text)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].github_url, "https://github.com/example/repo")


if __name__ == "__main__":
    unittest.main()
