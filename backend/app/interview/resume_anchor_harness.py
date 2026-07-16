from __future__ import annotations

import re
from typing import Any

from app.interview.resume_anchor_schema import ANCHOR_PRIORITY, ensure_resume_blocks, make_anchor

_GENERIC_REJECT_PATTERNS = (
    r"^education(?:\s+education)?$",
    r"^教育(?:经历|背景)?$",
    r"^skills?$",
    r"^项目经历(?:\s+experience)?$",
    r"^工作经历(?:\s+experience)?$",
    r"^实习经历(?:\s+experience)?$",
    r"^profile$",
    r"^summary$",
)
_NAME_ONLY_RE = re.compile(r"^[\u4e00-\u9fff]{2,4}$|^[A-Za-z][A-Za-z\s]{1,30}$")
_SKILL_WORD_RE = re.compile(r"^(agent|rag|gpt|llm|python|java|redis|mysql|docker)$", re.IGNORECASE)
_PROJECT_KEYWORD_RE = re.compile(r"(agent|rag|项目|平台|系统|助手|审查|开发|实践|模型实践|workflow|pipeline|assistant)", re.IGNORECASE)
_INTERNSHIP_RE = re.compile(r"(实习|intern)", re.IGNORECASE)
_WORK_RE = re.compile(r"(工程师|经理|负责人|公司|有限公司|engineer|manager|developer)", re.IGNORECASE)
_EDU_PROJECT_RE = re.compile(r"(毕设|毕业设计|课程设计|竞赛|大创|capstone)", re.IGNORECASE)
_TEMPLATE_NOISE_RE = re.compile(r"^[★☆•·#\-\s]*ai(?:\s*(增强开发|效率开发|开发))?$", re.IGNORECASE)
_AWARD_NOISE_RE = re.compile(r"(院级奖项|校级奖项|项目\d+次|奖项\d+次|获奖)", re.IGNORECASE)
_METHOD_TEMPLATE_NOISE_RE = re.compile(
    r"(prompt\s*模板|模板|项目复盘|复盘等场景|场景\s*prompt|工具链|编程工具|antigravity|"
    r"function\s*calling|harness\s*engineering|约束审查链路|方法论|高效率开发)",
    re.IGNORECASE,
)
_REAL_EXPERIENCE_SIGNAL_RE = re.compile(
    r"(\d{4}[./-]\d{1,2}|负责|实现|构建|设计|优化|上线|落地|交付|提升|"
    r"公司|有限公司|实习|intern|项目名称|项目职责|个人职责|担任|主导|参与开发)",
    re.IGNORECASE,
)
_FRAGMENT_PUNCT_RE = re.compile(r"[,，;；:：、]")
_FRAGMENT_HINT_RE = re.compile(
    r"(具备|负责|熟悉|参与|协作|能力|经验|实现|优化|设计|支持|开发|introduced|responsible|familiar|experienced)",
    re.IGNORECASE,
)


def build_resume_anchors(resume_blocks: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = ensure_resume_blocks(resume_blocks)
    anchors: list[dict[str, Any]] = []
    order = 0

    for item in blocks["work_experience"]:
        name = " ".join(part for part in (item.get("organization"), item.get("title") or item.get("role")) if part).strip()
        anchors.append(
            make_anchor(
                anchor_type="work",
                name=name or item.get("description") or "",
                evidence=_compose_evidence(item),
                keywords=_extract_keywords(item),
                source_block="work_experience",
                order=order,
            )
        )
        order += 1

    for item in blocks["internship_experience"]:
        name = " ".join(part for part in (item.get("organization"), item.get("title") or item.get("role")) if part).strip()
        anchors.append(
            make_anchor(
                anchor_type="internship",
                name=name or item.get("description") or "",
                evidence=_compose_evidence(item),
                keywords=_extract_keywords(item),
                source_block="internship_experience",
                order=order,
            )
        )
        order += 1

    for item in blocks["projects"]:
        anchors.append(
            make_anchor(
                anchor_type="project",
                name=item.get("title") or item.get("description") or "",
                evidence=_compose_evidence(item),
                keywords=_extract_keywords(item),
                source_block="projects",
                order=order,
            )
        )
        order += 1

    for item in blocks["education"]:
        if _EDU_PROJECT_RE.search(_compose_evidence(item)):
            anchors.append(
                make_anchor(
                    anchor_type="education_project",
                    name=item.get("title") or item.get("description") or "",
                    evidence=_compose_evidence(item),
                    keywords=_extract_keywords(item),
                    source_block="education",
                    order=order,
                )
            )
            order += 1

    for item in blocks["skills"]:
        title = str(item.get("title") or "").strip()
        if _PROJECT_KEYWORD_RE.search(title):
            anchors.append(
                make_anchor(
                    anchor_type="skill_practice",
                    name=title,
                    evidence=title,
                    keywords=[title],
                    source_block="skills",
                    order=order,
                )
            )
            order += 1
    return anchors


def validate_resume_analysis(
    resume_blocks: dict[str, Any],
    anchors: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    valid: list[dict[str, Any]] = []
    reasons: list[str] = []
    for anchor in anchors:
        reason = reject_anchor_reason(anchor)
        if reason:
            anchor["rejected_reason"] = reason
            reasons.append(reason)
            continue
        anchor["score"] = score_anchor(anchor)
        valid.append(anchor)
    valid.sort(key=lambda item: (-int(item.get("score") or 0), int(item.get("order") or 999)))
    if not valid:
        reasons.append("no_valid_anchor")
    return valid[:8], reasons


def choose_best_opening_anchor(anchors: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not anchors:
        return None
    return sorted(
        anchors,
        key=lambda item: (-int(item.get("score") or 0), int(item.get("order") or 999)),
    )[0]


def reject_anchor_reason(anchor: dict[str, Any]) -> str | None:
    name = str(anchor.get("name") or "").strip()
    evidence = str(anchor.get("evidence") or "").strip()
    joined = f"{name} {evidence}".strip()
    lowered = name.lower()
    if not name:
        return "empty_name"
    if any(re.match(pattern, lowered, re.IGNORECASE) for pattern in _GENERIC_REJECT_PATTERNS):
        return "generic_section_header"
    if _SKILL_WORD_RE.match(name) and anchor.get("type") not in {"project", "work", "internship"}:
        return "short_skill_only"
    if len(name) <= 2:
        return "too_short"
    if anchor.get("source_block") == "education" and not _EDU_PROJECT_RE.search(joined):
        return "education_not_opening_anchor"
    if _looks_like_person_name(name) and anchor.get("source_block") != "profile":
        return "name_only"
    if _TEMPLATE_NOISE_RE.match(name):
        return "template_title_only"
    if _METHOD_TEMPLATE_NOISE_RE.search(joined) and not _REAL_EXPERIENCE_SIGNAL_RE.search(joined):
        return "method_template_noise"
    if _AWARD_NOISE_RE.search(name) and anchor.get("type") not in {"work", "internship", "project"}:
        return "award_noise"
    if _FRAGMENT_PUNCT_RE.search(name) and _FRAGMENT_HINT_RE.search(name) and not re.search(r"\d{4}[./-]\d{1,2}", joined):
        return "fragment_like_title"
    return None


def score_anchor(anchor: dict[str, Any]) -> int:
    anchor_type = str(anchor.get("type") or "")
    score = ANCHOR_PRIORITY.get(anchor_type, 0)
    name = str(anchor.get("name") or "")
    evidence = str(anchor.get("evidence") or "")
    joined = f"{name} {evidence}"

    if _PROJECT_KEYWORD_RE.search(joined):
        score += 80
    if _INTERNSHIP_RE.search(joined):
        score += 40
    if _WORK_RE.search(joined):
        score += 35
    if re.search(r"\d{4}[./-]\d{1,2}", joined):
        score += 20
    if len(name) >= 8:
        score += 15
    if len(evidence) >= 20:
        score += 15
    if anchor_type == "skill_practice":
        score -= 40
    if _TEMPLATE_NOISE_RE.match(name):
        score -= 160
    if _AWARD_NOISE_RE.search(joined):
        score -= 120
    return score


def _compose_evidence(item: dict[str, Any]) -> str:
    return " ".join(
        part for part in (
            str(item.get("title") or "").strip(),
            str(item.get("organization") or "").strip(),
            str(item.get("role") or "").strip(),
            str(item.get("date_range") or "").strip(),
            str(item.get("description") or "").strip(),
        ) if part
    ).strip()


def _extract_keywords(item: dict[str, Any]) -> list[str]:
    blob = _compose_evidence(item)
    raw = re.split(r"[\s,，、/|:：()（）\-]+", blob)
    return [token for token in raw if len(token) >= 2][:8]


def _looks_like_person_name(value: str) -> bool:
    if any(ch.isdigit() for ch in value):
        return False
    if _PROJECT_KEYWORD_RE.search(value):
        return False
    return bool(_NAME_ONLY_RE.match(value))
