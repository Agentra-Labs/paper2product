import unittest

from paper2product.models import PaperContent
from paper2product.reporting import build_report


class ReportingTests(unittest.TestCase):
    def test_build_report_includes_supporting_sources_sections(self):
        paper = PaperContent(
            paper_id="2603.09229",
            source="arxiv",
            title="Example Paper",
            authors=["Alice", "Bob"],
            abstract="Abstract",
            full_text="Full text",
            sections={},
            figures_captions=[],
            tables_text=[],
            references_titles=[],
        )
        report = build_report(
            paper=paper,
            primitives="Primitives",
            pain="Pain",
            pain_sources="### Supporting Sources\n- [Source](https://example.com)",
            crosspoll="Cross",
            infra="Infra",
            temporal="Temporal",
            temporal_sources="### Supporting Sources\n- [Temporal](https://example.com/2)",
            redteam="Redteam",
            redteam_sources="### Supporting Sources\n- [Redteam](https://example.com/3)",
            final="Final",
            quality_review="### Quality Review\n- **Status**: Accepted",
        )
        self.assertIn("### Supporting Sources", report)
        self.assertIn("https://example.com/3", report)
        self.assertIn("## Quality Review", report)


if __name__ == "__main__":
    unittest.main()
