from __future__ import annotations

import json
import re
from typing import Any

from app.interview.resume_anchor_harness import choose_best_opening_anchor
from app.interview.resume_anchor_loop import extract_resume_analysis


def extract_keywords_from_text(text: str) -> list[str]:
    parts = re.split(r"[\s,，、/|:：()（）\-]+", str(text or ""))
    return [part.strip() for part in parts if len(part.strip()) >= 2][:8]


def is_contact_or_intent_line(text: str) -> bool:
    lowered = str(text or "").lower()
    has_contact_label = any(label in str(text or "") for label in ("电话", "手机", "微信", "邮箱", "联系方式", "求职意向", "email"))
    has_phone = bool(re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", str(text or "")))
    has_email = bool(re.search(r"[\w.+-]+@[\w.-]+\.\w+", lowered))
    return has_contact_label or has_phone or has_email


def extract_resume_anchors(
    resume_snapshot: str,
    *,
    structured_resume: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return extract_resume_analysis(
        resume_snapshot,
        structured_resume=structured_resume,
    )["anchors"]


def select_opening_anchor(resume_anchors: list[dict[str, Any]]) -> dict[str, Any] | None:
    return choose_best_opening_anchor(resume_anchors)


def extract_resume_anchor_payload(
    resume_snapshot: str,
    *,
    structured_resume: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return extract_resume_analysis(
        resume_snapshot,
        structured_resume=structured_resume,
    )


def try_load_resume_json(resume_snapshot: str) -> dict[str, Any] | None:
    candidate = (resume_snapshot or "").strip()
    if not candidate.startswith("{"):
        return None
    try:
        value = json.loads(candidate)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None
