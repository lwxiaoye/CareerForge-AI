from __future__ import annotations

from typing import Any, Callable

from app.interview.resume_anchor_harness import (
    build_resume_anchors,
    choose_best_opening_anchor,
    validate_resume_analysis,
)
from app.interview.resume_anchor_repair import (
    rebalance_section_blocks,
    repair_anchor_candidates,
    summarize_failure_reason,
)
from app.interview.resume_anchor_schema import empty_resume_analysis, ensure_resume_blocks
from app.interview.resume_block_extractor import (
    extract_blocks_from_structured_resume,
    split_resume_blocks,
    try_parse_structured_resume,
)

Strategy = Callable[[str, dict[str, Any] | None], dict[str, list[dict[str, Any]]]]


def extract_resume_analysis(
    resume_text: str,
    *,
    structured_resume: dict[str, Any] | None = None,
    max_attempts: int = 4,
) -> dict[str, Any]:
    result = empty_resume_analysis()
    attempts: list[dict[str, Any]] = []
    last_blocks = ensure_resume_blocks({})

    strategies = _build_strategies()
    for attempt_index, strategy in enumerate(strategies[: max(1, min(max_attempts, 4))], start=1):
        resume_blocks = ensure_resume_blocks(strategy(resume_text, structured_resume))
        anchors = build_resume_anchors(resume_blocks)
        valid_anchors, reasons = validate_resume_analysis(resume_blocks, anchors)
        best_anchor = choose_best_opening_anchor(valid_anchors)
        confidence = _estimate_confidence(resume_blocks, valid_anchors, best_anchor)
        failure_reason = summarize_failure_reason(resume_blocks, len(valid_anchors))

        attempts.append(
            {
                "attempt": attempt_index,
                "strategy": strategy.__name__,
                "block_counts": {key: len(value) for key, value in resume_blocks.items()},
                "valid_anchor_count": len(valid_anchors),
                "reasons": reasons,
                "failure_reason": failure_reason,
                "confidence": confidence,
            }
        )
        last_blocks = resume_blocks
        if best_anchor:
            result["resume_blocks"] = resume_blocks
            result["anchors"] = valid_anchors
            result["best_opening_anchor"] = best_anchor
            result["confidence"] = confidence
            result["attempts"] = attempts
            return result

    fallback = _build_fallback(last_blocks, attempts)
    fallback["attempts"] = attempts
    return fallback


def _build_strategies() -> list[Strategy]:
    return [
        _strategy_structured_resume,
        _strategy_json_text,
        _strategy_section_rebalance,
        _strategy_anchor_repair,
    ]


def _strategy_structured_resume(resume_text: str, structured_resume: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    if structured_resume:
        return extract_blocks_from_structured_resume(structured_resume)
    return ensure_resume_blocks({})


def _strategy_json_text(resume_text: str, structured_resume: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    parsed = try_parse_structured_resume(resume_text)
    return parsed or ensure_resume_blocks({})


def _strategy_section_rebalance(resume_text: str, structured_resume: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    return rebalance_section_blocks(split_resume_blocks(resume_text))


def _strategy_anchor_repair(resume_text: str, structured_resume: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    return repair_anchor_candidates(resume_text, split_resume_blocks(resume_text))


def _build_fallback(last_blocks: dict[str, Any], attempts: list[dict[str, Any]]) -> dict[str, Any]:
    result = empty_resume_analysis()
    result["resume_blocks"] = ensure_resume_blocks(last_blocks)
    result["anchors"] = []
    result["best_opening_anchor"] = None
    result["confidence"] = 0.15 if any(any(values) for values in last_blocks.values()) else 0.0
    result["fallback_reason"] = "resume_anchor_extraction_failed"
    if attempts:
        result["fallback_reason"] = f"resume_anchor_extraction_failed:{attempts[-1]['failure_reason']}"
    return result


def _estimate_confidence(
    resume_blocks: dict[str, Any],
    anchors: list[dict[str, Any]],
    best_anchor: dict[str, Any] | None,
) -> float:
    if not best_anchor:
        return 0.0
    score = 0.35
    if resume_blocks["work_experience"] or resume_blocks["internship_experience"]:
        score += 0.2
    if resume_blocks["projects"]:
        score += 0.2
    if len(anchors) >= 2:
        score += 0.1
    if best_anchor.get("type") in {"work", "internship", "project"}:
        score += 0.1
    if best_anchor.get("source_block") in {"work_experience", "internship_experience", "projects"}:
        score += 0.05
    return min(score, 0.98)
