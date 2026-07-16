from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from app.interview.resume_anchor_schema import ensure_resume_blocks, make_block_item

_PROJECT_HINT_RE = re.compile(r"(agent|rag|项目|平台|系统|助手|审查|开发|模型实践|gpt|claude|gemini)", re.IGNORECASE)
_INTERNSHIP_HINT_RE = re.compile(r"(实习|intern)", re.IGNORECASE)
_WORK_HINT_RE = re.compile(r"(公司|有限公司|工程师|负责人|经理|\bdeveloper\b|\bengineer\b|\bmanager\b)", re.IGNORECASE)
_EDUCATION_HINT_RE = re.compile(r"(教育|大学|学院|本科|硕士|博士|education)", re.IGNORECASE)
_NOISE_HINT_RE = re.compile(r"(姓名|name|电话|手机|邮箱|微信|求职意向|技术前瞻|学习热情|个人特长|自我评价)", re.IGNORECASE)
_DATE_RE = re.compile(r"\d{4}[./-]\d{1,2}(?:[./-]\d{1,2})?(?:\s*(?:-|–|—|至|to)\s*(?:\d{4}[./-]\d{1,2}(?:[./-]\d{1,2})?|至今|present|now))?", re.IGNORECASE)
_SHORT_SKILL_RE = re.compile(r"^(agent|rag|gpt|llm|redis|mysql|docker)$", re.IGNORECASE)
_SECTION_HEADER_RE = re.compile(r"^(项目经历|项目经验|工作经历|实习经历|教育经历|教育背景|skills?|profile|summary)(?:\s+[A-Za-z]+)?$", re.IGNORECASE)
_TITLE_NOISE_RE = re.compile(r"(项目表达|面试口述|奖项\d+次|项目\d+次)", re.IGNORECASE)
_TEMPLATE_PROJECT_RE = re.compile(r"^[★☆•·#\-\s]*ai(?:\s*(增强开发|效率开发|开发))", re.IGNORECASE)
_LONG_DESCRIPTION_RE = re.compile(r"(基于|负责|实现|构建|设计|优化|支持|通过|完成|提升|进行)", re.IGNORECASE)
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


def rebalance_section_blocks(resume_blocks: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    blocks = ensure_resume_blocks(resume_blocks)
    rebalanced = ensure_resume_blocks(deepcopy(blocks))
    candidate_lines = _collect_candidate_lines(blocks)

    for line in candidate_lines:
        target = _infer_target_block(line)
        if not target:
            continue
        item = _line_to_block_item(line, source="section_repair")
        if not item:
            continue
        if not _block_contains_line(rebalanced[target], line):
            rebalanced[target].append(item)
    return rebalanced


def repair_anchor_candidates(resume_text: str, resume_blocks: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    repaired = rebalance_section_blocks(resume_blocks)
    lines = [line.strip() for line in (resume_text or "").splitlines() if line.strip()]
    for index, line in enumerate(lines[:24]):
        if _NOISE_HINT_RE.search(line):
            continue
        target = _infer_target_block(line, allow_project_fallback=True)
        if not target:
            continue
        description_parts = [line]
        if index + 1 < len(lines):
            next_line = lines[index + 1].strip()
            if next_line and not _NOISE_HINT_RE.search(next_line) and len(next_line) <= 120:
                description_parts.append(next_line)
        merged_line = "\n".join(description_parts)
        item = _line_to_block_item(merged_line, source="anchor_repair")
        if not item:
            continue
        if not _block_contains_line(repaired[target], line):
            repaired[target].append(item)
    return repaired


def summarize_failure_reason(resume_blocks: dict[str, Any], valid_anchor_count: int) -> str:
    blocks = ensure_resume_blocks(resume_blocks)
    non_empty = {key: value for key, value in blocks.items() if value}
    if not non_empty:
        return "no_blocks_extracted"
    if valid_anchor_count > 0:
        return "recovered"
    if non_empty.keys() <= {"education"}:
        return "only_education_detected"
    if non_empty.keys() <= {"skills"}:
        return "only_skills_detected"
    if non_empty.keys() <= {"profile"}:
        return "only_profile_detected"
    if not (blocks["work_experience"] or blocks["internship_experience"] or blocks["projects"]):
        return "no_project_work_internship_block"
    return "no_valid_anchor"


def _collect_candidate_lines(blocks: dict[str, list[dict[str, Any]]]) -> list[str]:
    lines: list[str] = []
    for block_name, items in blocks.items():
        for item in items:
            for value in (
                item.get("title"),
                item.get("organization"),
                item.get("role"),
                item.get("description"),
            ):
                text = str(value or "").strip()
                if not text:
                    continue
                if block_name == "education" and _EDUCATION_HINT_RE.search(text) and not _PROJECT_HINT_RE.search(text):
                    continue
                lines.extend(part.strip() for part in text.splitlines() if part.strip())
    return lines


def _infer_target_block(line: str, *, allow_project_fallback: bool = False) -> str | None:
    if not line or _NOISE_HINT_RE.search(line) or _SECTION_HEADER_RE.match(line) or _SHORT_SKILL_RE.match(line) or _TITLE_NOISE_RE.search(line) or _TEMPLATE_PROJECT_RE.match(line):
        return None
    if _looks_like_method_template_noise(line):
        return None
    if _EDUCATION_HINT_RE.search(line) and not (_PROJECT_HINT_RE.search(line) or _WORK_HINT_RE.search(line) or _INTERNSHIP_HINT_RE.search(line)):
        return None
    if _INTERNSHIP_HINT_RE.search(line):
        return "internship_experience"
    if _WORK_HINT_RE.search(line) and not _PROJECT_HINT_RE.search(line):
        return "work_experience"
    if _PROJECT_HINT_RE.search(line):
        if len(line) > 32 and _LONG_DESCRIPTION_RE.search(line) and not _DATE_RE.search(line) and "模型实践" not in line:
            return None
        return "projects"
    if allow_project_fallback and _DATE_RE.search(line) and not _EDUCATION_HINT_RE.search(line):
        return "projects"
    return None


def _line_to_block_item(line: str, *, source: str) -> dict[str, Any] | None:
    cleaned = str(line or "").strip()
    if not cleaned:
        return None
    if _looks_like_method_template_noise(cleaned):
        return None
    date_match = _DATE_RE.search(cleaned)
    date_range = date_match.group(0) if date_match else ""
    title = cleaned.replace(date_range, "").strip(" -|")
    if "：" in title:
        prefix, suffix = title.split("：", 1)
        if prefix.strip() in {"项目", "项目经历", "项目经验", "Project", "Projects"} and suffix.strip():
            title = suffix.strip()
        elif len(prefix.strip()) <= 12:
            title = prefix.strip()
    elif ":" in title:
        prefix, suffix = title.split(":", 1)
        if prefix.strip().lower() in {"project", "projects"} and suffix.strip():
            title = suffix.strip()
        elif len(prefix.strip()) <= 12:
            title = prefix.strip()
    title = title[:80].strip()
    if not title or _SHORT_SKILL_RE.match(title) or _SECTION_HEADER_RE.match(title) or _TITLE_NOISE_RE.search(title) or _TEMPLATE_PROJECT_RE.match(title):
        return None
    return make_block_item(
        title=title,
        date_range=date_range,
        description=cleaned[:240],
        source=source,
    )


def _looks_like_method_template_noise(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return False
    if not _METHOD_TEMPLATE_NOISE_RE.search(text):
        return False
    return not _REAL_EXPERIENCE_SIGNAL_RE.search(text)


def _block_contains_line(items: list[dict[str, Any]], line: str) -> bool:
    compact = str(line or "").strip()
    for item in items:
        joined = " ".join(
            str(item.get(key) or "").strip()
            for key in ("title", "organization", "role", "description")
        )
        if compact and compact in joined:
            return True
    return False
