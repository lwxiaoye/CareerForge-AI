from __future__ import annotations

from copy import deepcopy
from typing import Any

RESUME_BLOCK_KEYS = (
    "work_experience",
    "internship_experience",
    "projects",
    "education",
    "skills",
    "profile",
)

ANCHOR_PRIORITY = {
    "work": 500,
    "internship": 450,
    "project": 400,
    "education_project": 300,
    "skill_practice": 200,
    "skill": 100,
    "text": 50,
}

EMPTY_RESUME_BLOCKS = {
    "work_experience": [],
    "internship_experience": [],
    "projects": [],
    "education": [],
    "skills": [],
    "profile": [],
}


def empty_resume_analysis() -> dict[str, Any]:
    return {
        "resume_blocks": deepcopy(EMPTY_RESUME_BLOCKS),
        "anchors": [],
        "best_opening_anchor": None,
        "fallback_reason": None,
        "confidence": 0.0,
        "attempts": [],
    }


def ensure_resume_blocks(blocks: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    normalized: dict[str, list[dict[str, Any]]] = {key: [] for key in RESUME_BLOCK_KEYS}
    if not isinstance(blocks, dict):
        return normalized
    for key in RESUME_BLOCK_KEYS:
        value = blocks.get(key)
        if isinstance(value, list):
            normalized[key] = [item for item in value if isinstance(item, dict)]
    return normalized


def make_block_item(
    *,
    title: str = "",
    organization: str = "",
    role: str = "",
    date_range: str = "",
    description: str = "",
    source: str = "",
) -> dict[str, Any]:
    return {
        "title": str(title or "").strip(),
        "organization": str(organization or "").strip(),
        "role": str(role or "").strip(),
        "date_range": str(date_range or "").strip(),
        "description": str(description or "").strip(),
        "source": str(source or "").strip(),
    }


def make_anchor(
    *,
    anchor_type: str,
    name: str,
    evidence: str = "",
    keywords: list[str] | None = None,
    source_block: str = "",
    order: int | None = None,
    score: int = 0,
    rejected_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "type": anchor_type,
        "name": str(name or "").strip(),
        "evidence": str(evidence or "").strip(),
        "keywords": [str(item).strip() for item in (keywords or []) if str(item).strip()],
        "source_block": str(source_block or "").strip(),
        "order": order,
        "score": score,
        "rejected_reason": rejected_reason,
    }
