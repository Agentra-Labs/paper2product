from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class CreditDecision:
    credits_spent: int
    free_report_used: bool


class ServiceStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                create table if not exists profiles (
                    id text primary key,
                    display_name text not null,
                    credit_balance integer not null default 3,
                    last_free_report_on text,
                    created_at text not null
                );

                create table if not exists report_jobs (
                    id text primary key,
                    user_id text not null,
                    paper_ref text not null,
                    model text,
                    title text,
                    paper_id text,
                    summary text,
                    markdown text,
                    status text not null,
                    credits_spent integer not null default 0,
                    error_message text,
                    created_at text not null,
                    updated_at text not null
                );

                create table if not exists credit_ledger (
                    id text primary key,
                    user_id text not null,
                    report_job_id text,
                    delta integer not null,
                    reason text not null,
                    created_at text not null
                );

                create table if not exists feedback_submissions (
                    id text primary key,
                    user_id text not null,
                    report_job_id text not null,
                    honesty_rating integer not null,
                    usefulness_rating integer not null,
                    detailed_feedback text not null,
                    honesty_score integer not null,
                    usefulness_score integer not null,
                    specificity_score integer not null,
                    overall_score integer not null,
                    credits_awarded integer not null default 0,
                    rationale text not null,
                    scoring_mode text not null,
                    created_at text not null
                );
                """
            )
            connection.commit()

    def ensure_user(self, user_id: str, display_name: str | None = None) -> None:
        now = utc_now().isoformat()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                insert into profiles (id, display_name, created_at)
                values (?, ?, ?)
                on conflict(id) do update set
                    display_name = excluded.display_name
                """,
                (user_id, display_name or "Reviewer", now),
            )
            connection.commit()

    def _allocate_report_credit(self, connection: sqlite3.Connection, user_id: str) -> CreditDecision:
        row = connection.execute(
            "select credit_balance, last_free_report_on from profiles where id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown user: {user_id}")

        today = date.today().isoformat()
        if row["last_free_report_on"] != today:
            connection.execute(
                "update profiles set last_free_report_on = ? where id = ?",
                (today, user_id),
            )
            return CreditDecision(credits_spent=0, free_report_used=True)

        balance = int(row["credit_balance"])
        if balance <= 0:
            raise ValueError("No credits available. Submit feedback or wait for the next daily free report.")

        connection.execute(
            "update profiles set credit_balance = credit_balance - 1 where id = ?",
            (user_id,),
        )
        return CreditDecision(credits_spent=1, free_report_used=False)

    def create_report_job(self, *, user_id: str, paper_ref: str, model: str | None) -> dict[str, Any]:
        self.ensure_user(user_id)
        job_id = str(uuid.uuid4())
        now = utc_now().isoformat()

        with closing(self._connect()) as connection:
            decision = self._allocate_report_credit(connection, user_id)
            connection.execute(
                """
                insert into report_jobs (
                    id, user_id, paper_ref, model, status, credits_spent, created_at, updated_at
                ) values (?, ?, ?, ?, 'queued', ?, ?, ?)
                """,
                (job_id, user_id, paper_ref, model, decision.credits_spent, now, now),
            )
            if decision.credits_spent:
                connection.execute(
                    """
                    insert into credit_ledger (id, user_id, report_job_id, delta, reason, created_at)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), user_id, job_id, -1, "report_generation", now),
                )
            connection.commit()

        return {
            "id": job_id,
            "status": "queued",
            "creditsSpent": decision.credits_spent,
        }

    def mark_job_running(self, job_id: str) -> None:
        self._update_job(job_id, status="running")

    def complete_report_job(
        self,
        *,
        job_id: str,
        title: str,
        paper_id: str,
        summary: str,
        markdown: str,
    ) -> None:
        self._update_job(
            job_id,
            status="completed",
            title=title,
            paper_id=paper_id,
            summary=summary,
            markdown=markdown,
            error_message=None,
        )

    def fail_report_job(self, job_id: str, error_message: str) -> None:
        self._update_job(job_id, status="failed", error_message=error_message)

    def _update_job(self, job_id: str, **updates: Any) -> None:
        if not updates:
            return
        updates["updated_at"] = utc_now().isoformat()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [job_id]
        with closing(self._connect()) as connection:
            connection.execute(f"update report_jobs set {assignments} where id = ?", values)
            connection.commit()

    def get_report_job(self, job_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "select * from report_jobs where id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None

        return {
            "id": row["id"],
            "paperId": row["paper_id"] or row["paper_ref"],
            "title": row["title"] or row["paper_ref"],
            "summary": row["summary"] or "Report is still being generated.",
            "markdown": row["markdown"] or "# Report pending",
            "status": row["status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "creditsSpent": row["credits_spent"],
            "errorMessage": row["error_message"],
        }

    def record_feedback(
        self,
        *,
        user_id: str,
        report_job_id: str,
        honesty_rating: int,
        usefulness_rating: int,
        detailed_feedback: str,
        score: dict[str, Any],
    ) -> dict[str, Any]:
        self.ensure_user(user_id)
        feedback_id = str(uuid.uuid4())
        created_at = utc_now().isoformat()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                insert into feedback_submissions (
                    id, user_id, report_job_id, honesty_rating, usefulness_rating, detailed_feedback,
                    honesty_score, usefulness_score, specificity_score, overall_score,
                    credits_awarded, rationale, scoring_mode, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id,
                    user_id,
                    report_job_id,
                    honesty_rating,
                    usefulness_rating,
                    detailed_feedback,
                    score["honesty_score"],
                    score["usefulness_score"],
                    score["specificity_score"],
                    score["overall_score"],
                    score["credits_awarded"],
                    score["rationale"],
                    score["scoring_mode"],
                    created_at,
                ),
            )
            if score["credits_awarded"]:
                connection.execute(
                    "update profiles set credit_balance = credit_balance + ? where id = ?",
                    (score["credits_awarded"], user_id),
                )
                connection.execute(
                    """
                    insert into credit_ledger (id, user_id, report_job_id, delta, reason, created_at)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        user_id,
                        report_job_id,
                        score["credits_awarded"],
                        "feedback_reward",
                        created_at,
                    ),
                )
            connection.commit()

        return {
            "feedbackId": feedback_id,
            "honestyScore": score["honesty_score"],
            "usefulnessScore": score["usefulness_score"],
            "specificityScore": score["specificity_score"],
            "score": score["overall_score"],
            "creditsAwarded": score["credits_awarded"],
            "rationale": score["rationale"],
            "scoringMode": score["scoring_mode"],
        }

    def get_dashboard_snapshot(self, user_id: str) -> dict[str, Any]:
        self.ensure_user(user_id)
        with closing(self._connect()) as connection:
            profile = connection.execute(
                "select * from profiles where id = ?",
                (user_id,),
            ).fetchone()
            reports = connection.execute(
                """
                select id, coalesce(paper_id, paper_ref) as paper_id, coalesce(title, paper_ref) as title,
                       coalesce(summary, 'Report in progress.') as summary, created_at, status, credits_spent
                from report_jobs where user_id = ?
                order by created_at desc
                limit 8
                """,
                (user_id,),
            ).fetchall()
            feedback = connection.execute(
                """
                select id, report_job_id, created_at, honesty_score, usefulness_score, credits_awarded, rationale
                from feedback_submissions where user_id = ?
                order by created_at desc
                limit 5
                """,
                (user_id,),
            ).fetchall()
            stats = connection.execute(
                """
                select
                    count(*) as generated_reports,
                    sum(case when status = 'completed' then 1 else 0 end) as completed_reports
                from report_jobs where user_id = ?
                """,
                (user_id,),
            ).fetchone()
            feedback_stats = connection.execute(
                """
                select
                    count(*) as feedback_count,
                    round(avg(honesty_score), 0) as avg_honesty,
                    sum(credits_awarded) as credits_earned
                from feedback_submissions where user_id = ?
                """,
                (user_id,),
            ).fetchone()

        free_remaining = profile["last_free_report_on"] != date.today().isoformat()
        return {
            "user": {
                "id": user_id,
                "name": profile["display_name"],
                "role": "Reader / Reviewer",
            },
            "credits": {
                "balance": profile["credit_balance"],
                "freeReportRemainingToday": free_remaining,
                "earnedToday": feedback_stats["credits_earned"] or 0,
            },
            "stats": {
                "generatedReports": stats["generated_reports"] or 0,
                "feedbackAccepted": feedback_stats["feedback_count"] or 0,
                "avgHonestyScore": int(feedback_stats["avg_honesty"] or 0),
            },
            "reports": [
                {
                    "id": row["id"],
                    "paperId": row["paper_id"],
                    "title": row["title"],
                    "summary": row["summary"],
                    "createdAt": row["created_at"],
                    "status": row["status"],
                    "creditsSpent": row["credits_spent"],
                }
                for row in reports
            ],
            "recentFeedback": [
                {
                    "id": row["id"],
                    "reportId": row["report_job_id"],
                    "createdAt": row["created_at"],
                    "honestyScore": row["honesty_score"],
                    "usefulnessScore": row["usefulness_score"],
                    "creditsAwarded": row["credits_awarded"],
                    "note": row["rationale"],
                }
                for row in feedback
            ],
        }

    def get_learning_digest(self, *, limit: int = 6) -> str:
        with closing(self._connect()) as connection:
            reports = connection.execute(
                """
                select coalesce(title, paper_ref) as title,
                       coalesce(summary, 'Report in progress.') as summary,
                       created_at
                from report_jobs
                where status = 'completed'
                order by updated_at desc
                limit ?
                """,
                (limit,),
            ).fetchall()
            feedback = connection.execute(
                """
                select coalesce(rationale, '') as rationale,
                       honesty_score,
                       usefulness_score,
                       specificity_score,
                       overall_score,
                       created_at
                from feedback_submissions
                order by created_at desc
                limit ?
                """,
                (limit,),
            ).fetchall()

        lines: list[str] = []
        if reports:
            lines.append("### Recent Completed Reports")
            for row in reports:
                lines.append(
                    f"- {row['title']} — {row['summary']} ({row['created_at'][:10]})"
                )

        if feedback:
            if lines:
                lines.append("")
            lines.append("### Recent Feedback Signals")
            for row in feedback:
                rationale = row["rationale"].strip()[:180]
                if not rationale:
                    rationale = "No rationale provided."
                lines.append(
                    "- score "
                    f"{row['overall_score']} | honesty {row['honesty_score']} | "
                    f"usefulness {row['usefulness_score']} | specificity {row['specificity_score']} "
                    f"— {rationale}"
                )

        return "\n".join(lines)
