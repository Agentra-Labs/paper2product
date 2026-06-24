from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from paper2product.feedback import heuristic_feedback_score
from paper2product.service_store import ServiceStore


class ServiceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = ServiceStore(Path(self.tmpdir.name) / "service.db")
        self.store.ensure_user("reviewer-1", "Reviewer One")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_first_report_per_day_is_free_then_paid(self) -> None:
        first = self.store.create_report_job(user_id="reviewer-1", paper_ref="2603.08127", model=None)
        second = self.store.create_report_job(user_id="reviewer-1", paper_ref="2603.09229", model=None)

        self.assertEqual(first["creditsSpent"], 0)
        self.assertEqual(second["creditsSpent"], 1)

        dashboard = self.store.get_dashboard_snapshot("reviewer-1")
        self.assertEqual(dashboard["credits"]["balance"], 2)
        self.assertFalse(dashboard["credits"]["freeReportRemainingToday"])

    def test_feedback_reward_adds_credits(self) -> None:
        job = self.store.create_report_job(user_id="reviewer-1", paper_ref="2603.08127", model=None)
        self.store.complete_report_job(
            job_id=job["id"],
            title="Example report",
            paper_id="2603.08127",
            summary="Summary",
            markdown="# Report",
        )

        score = heuristic_feedback_score(
            honesty_rating=5,
            usefulness_rating=5,
            detailed_feedback=(
                "The buyer logic is strong because the report names the operator and the rollout risk, "
                "but the moat argument is weaker than the GTM section."
            ),
        )
        result = self.store.record_feedback(
            user_id="reviewer-1",
            report_job_id=job["id"],
            honesty_rating=5,
            usefulness_rating=5,
            detailed_feedback="Specific review feedback",
            score=score.as_dict(),
        )

        dashboard = self.store.get_dashboard_snapshot("reviewer-1")
        self.assertGreaterEqual(result["creditsAwarded"], 1)
        self.assertGreaterEqual(dashboard["credits"]["balance"], 4)

    def test_heuristic_feedback_score_rewards_specificity(self) -> None:
        weak = heuristic_feedback_score(
            honesty_rating=3,
            usefulness_rating=3,
            detailed_feedback="Looks good.",
        )
        strong = heuristic_feedback_score(
            honesty_rating=5,
            usefulness_rating=5,
            detailed_feedback=(
                "The report is honest because it calls out buyer ambiguity, GTM risk, and weak moat logic. "
                "The strongest section is the deployment risk analysis."
            ),
        )

        self.assertGreater(strong.overall_score, weak.overall_score)
        self.assertGreaterEqual(strong.credits_awarded, weak.credits_awarded)

    def test_learning_digest_includes_recent_reports_and_feedback(self) -> None:
        job = self.store.create_report_job(user_id="reviewer-1", paper_ref="2603.08127", model=None)
        self.store.complete_report_job(
            job_id=job["id"],
            title="Example report",
            paper_id="2603.08127",
            summary="Summary",
            markdown="# Report",
        )
        score = heuristic_feedback_score(
            honesty_rating=4,
            usefulness_rating=4,
            detailed_feedback="The report is specific because it names the buyer and moat risk.",
        )
        self.store.record_feedback(
            user_id="reviewer-1",
            report_job_id=job["id"],
            honesty_rating=4,
            usefulness_rating=4,
            detailed_feedback="Specific feedback with buyer and moat comments.",
            score=score.as_dict(),
        )

        digest = self.store.get_learning_digest(limit=3)
        self.assertIn("Recent Completed Reports", digest)
        self.assertIn("Recent Feedback Signals", digest)
        self.assertIn("Example report", digest)


if __name__ == "__main__":
    unittest.main()
