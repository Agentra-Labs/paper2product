from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

from .backend import build_openai_compatible_backend
from .errors import AgentExecutionError

SCORING_PROMPT = """\
You score reviewer feedback for an AI-generated product report.

Return strict JSON with these integer keys from 0 to 100:
- honesty_score
- usefulness_score
- specificity_score
- overall_score
- credits_awarded
- rationale

Scoring rules:
- Reward concrete criticism and clear reasoning.
- Penalize generic praise, empty sentiment, and vague reactions.
- Award 2 credits for excellent feedback, 1 for solid feedback, 0 otherwise.
- Keep rationale to one short sentence.
"""


@dataclass(slots=True)
class FeedbackScore:
    honesty_score: int
    usefulness_score: int
    specificity_score: int
    overall_score: int
    credits_awarded: int
    rationale: str
    scoring_mode: str

    def as_dict(self) -> dict[str, int | str]:
        return asdict(self)


def _clamp(value: int, floor: int = 0, ceiling: int = 100) -> int:
    return max(floor, min(ceiling, value))


def heuristic_feedback_score(
    *,
    honesty_rating: int,
    usefulness_rating: int,
    detailed_feedback: str,
) -> FeedbackScore:
    feedback = detailed_feedback.strip()
    word_count = len(feedback.split())
    concrete_markers = sum(
        1 for marker in ("because", "risk", "buyer", "moat", "gtm", "assumption", "weak", "strong")
        if marker in feedback.lower()
    )
    specificity_score = _clamp(28 + word_count * 2 + concrete_markers * 6, 25, 96)
    honesty_score = _clamp(honesty_rating * 18 + concrete_markers * 4, 18, 98)
    usefulness_score = _clamp(usefulness_rating * 18 + min(word_count, 20), 18, 98)
    overall_score = round((honesty_score + usefulness_score + specificity_score) / 3)

    if overall_score >= 82:
        credits_awarded = 2
    elif overall_score >= 68:
        credits_awarded = 1
    else:
        credits_awarded = 0

    rationale = (
        "Specific and candid feedback earned reviewer credits."
        if credits_awarded
        else "Feedback was too generic to earn more credits."
    )
    return FeedbackScore(
        honesty_score=honesty_score,
        usefulness_score=usefulness_score,
        specificity_score=specificity_score,
        overall_score=overall_score,
        credits_awarded=credits_awarded,
        rationale=rationale,
        scoring_mode="heuristic",
    )


def _can_use_ai_scoring() -> bool:
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY"))


async def score_feedback(
    *,
    report_title: str,
    report_summary: str,
    honesty_rating: int,
    usefulness_rating: int,
    detailed_feedback: str,
    model: str | None = None,
) -> FeedbackScore:
    heuristic = heuristic_feedback_score(
        honesty_rating=honesty_rating,
        usefulness_rating=usefulness_rating,
        detailed_feedback=detailed_feedback,
    )
    if not _can_use_ai_scoring():
        return heuristic

    backend = build_openai_compatible_backend()
    try:
        payload = await backend.generate_text(
            system_prompt=SCORING_PROMPT,
            user_prompt=(
                f"Report title: {report_title}\n"
                f"Report summary: {report_summary}\n"
                f"Honesty rating: {honesty_rating}/5\n"
                f"Usefulness rating: {usefulness_rating}/5\n"
                f"Feedback:\n{detailed_feedback}\n"
            ),
            model=model or os.getenv("PAPER2PRODUCT_MODEL", "openai/gpt-4.1-mini"),
            phase="feedback scoring",
            max_tokens=240,
        )
        parsed = json.loads(payload)
    except (AgentExecutionError, ValueError, TypeError, json.JSONDecodeError):
        return heuristic

    def read_int(key: str, fallback: int) -> int:
        raw = parsed.get(key, fallback)
        if not isinstance(raw, int):
            return fallback
        return _clamp(raw)

    overall = read_int("overall_score", heuristic.overall_score)
    credits_awarded = parsed.get("credits_awarded", heuristic.credits_awarded)
    if not isinstance(credits_awarded, int):
        credits_awarded = heuristic.credits_awarded
    credits_awarded = max(0, min(2, credits_awarded))
    rationale = parsed.get("rationale", heuristic.rationale)
    if not isinstance(rationale, str):
        rationale = heuristic.rationale

    return FeedbackScore(
        honesty_score=read_int("honesty_score", heuristic.honesty_score),
        usefulness_score=read_int("usefulness_score", heuristic.usefulness_score),
        specificity_score=read_int("specificity_score", heuristic.specificity_score),
        overall_score=overall,
        credits_awarded=credits_awarded,
        rationale=rationale.strip() or heuristic.rationale,
        scoring_mode="ai",
    )
