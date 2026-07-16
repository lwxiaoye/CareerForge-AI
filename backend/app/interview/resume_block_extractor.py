from __future__ import annotations

import json
import re
from typing import Any

from app.interview.resume_anchor_schema import ensure_resume_blocks, make_block_item

_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "work_experience": (
        "工作经历",
        "工作经验",
        "work experience",
        "professional experience",
        "employment",
    ),
    "internship_experience": (
        "实习经历",
        "实习经验",
        "internship",
        "intern experience",
    ),
    "projects": (
        "项目经历",
        "项目经验",
        "项目",
        "projects",
        "project experience",
    ),
    "education": (
        "教育经历",
        "教育背景",
        "教育",
        "education",
    ),
    "skills": (
        "技能",
        "专业技能",
        "技能栈",
        "technical skills",
        "skills",
    ),
    "profile": (
        "个人信息",
        "基本信息",
        "自我评价",
        "个人总结",
        "profile",
        "summary",
    ),
}

_DATE_RANGE_RE = re.compile(
    r"(?P<date>"
    r"\d{4}[./-]\d{1,2}(?:[./-]\d{1,2})?"
    r"(?:\s*(?:-|–|—|至|to)\s*(?:\d{4}[./-]\d{1,2}(?:[./-]\d{1,2})?|至今|present|now))?"
    r")",
    re.IGNORECASE,
)
_NOISE_LINE_RE = re.compile(r"^\[pdf[^\]]*\]$", re.IGNORECASE)
_NAME_LINE_RE = re.compile(r"^(姓名|name)\s*[:：]", re.IGNORECASE)
_CONTACT_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+|(?<!\d)1[3-9]\d{9}(?!\d)")
_GENERIC_PROJECT_HEADER_RE = re.compile(
    r"^(?:[★☆•·#\-\d._\s]*)?(?:ai|agent|rag|llm|gpt|claude|gemini)(?:\s*(?:增强开发|应用开发|效率开发|开发|实践|工程化))?$",
    re.IGNORECASE,
)
_AWARD_NOISE_RE = re.compile(r"(院级奖项|校级奖项|竞赛|获奖|证书|项目\d+次|奖项\d+次)", re.IGNORECASE)
_DESCRIPTIVE_LINE_RE = re.compile(r"[，,。；;：:]|负责|实现|构建|设计|优化|支持|开发|基于", re.IGNORECASE)
_SHORT_SKILL_NOISE_RE = re.compile(r"^(agent|rag|gpt|llm|redis|mysql|docker)$", re.IGNORECASE)


def split_resume_blocks(text: str) -> dict[str, list[dict[str, Any]]]:
    blocks = ensure_resume_blocks({})
    current_block = "profile"
    current_lines: list[str] = []

    for raw_line in (text or "").splitlines():
        line = _clean_line(raw_line)
        if not line:
            continue
        mapped_block = _match_section(line)
        if mapped_block:
            current_block = mapped_block
            continue
        current_lines.append((current_block, line))

    block_lines: dict[str, list[str]] = {key: [] for key in blocks}
    for block_name, line in current_lines:
        block_lines[block_name].append(line)

    return {
        "work_experience": _parse_experience_lines(block_lines["work_experience"], default_source="text"),
        "internship_experience": _parse_experience_lines(block_lines["internship_experience"], default_source="text"),
        "projects": _parse_project_lines(block_lines["projects"], default_source="text"),
        "education": _parse_education_lines(block_lines["education"], default_source="text"),
        "skills": _parse_skill_lines(block_lines["skills"], default_source="text"),
        "profile": _parse_profile_lines(block_lines["profile"], default_source="text"),
    }


def extract_blocks_from_structured_resume(data: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    blocks = ensure_resume_blocks({})
    if not isinstance(data, dict):
        return blocks

    for item in data.get("experience") or []:
        if not isinstance(item, dict):
            continue
        target = "internship_experience" if _looks_like_internship(item) else "work_experience"
        blocks[target].append(
            make_block_item(
                title=item.get("position") or item.get("title") or "",
                organization=item.get("company") or item.get("organization") or "",
                date_range=item.get("date") or "",
                description=item.get("details") or item.get("description") or "",
                source="structured_resume",
            )
        )

    for item in data.get("projects") or []:
        if not isinstance(item, dict):
            continue
        blocks["projects"].append(
            make_block_item(
                title=item.get("name") or item.get("title") or "",
                role=item.get("role") or "",
                date_range=item.get("date") or "",
                description=item.get("description") or item.get("details") or "",
                source="structured_resume",
            )
        )

    for item in data.get("education") or []:
        if not isinstance(item, dict):
            continue
        blocks["education"].append(
            make_block_item(
                title=item.get("major") or "",
                organization=item.get("school") or "",
                role=item.get("degree") or "",
                date_range=_join_dates(item.get("start_date"), item.get("end_date")),
                description=item.get("description") or "",
                source="structured_resume",
            )
        )

    skills = data.get("skills")
    if isinstance(skills, str):
        blocks["skills"].extend(_parse_skill_lines(skills.splitlines(), default_source="structured_resume"))
    elif isinstance(skills, list):
        blocks["skills"].extend(
            make_block_item(title=str(skill).strip(), source="structured_resume")
            for skill in skills
            if str(skill).strip()
        )

    basic = data.get("basic")
    if isinstance(basic, dict):
        basic_text = " ".join(
            str(basic.get(key) or "").strip()
            for key in ("name", "target_position", "location")
            if str(basic.get(key) or "").strip()
        ).strip()
        if basic_text:
            blocks["profile"].append(make_block_item(description=basic_text, source="structured_resume"))

    self_evaluation = str(data.get("self_evaluation") or "").strip()
    if self_evaluation:
        blocks["profile"].append(make_block_item(description=self_evaluation, source="structured_resume"))
    return blocks


def try_parse_structured_resume(text: str) -> dict[str, list[dict[str, Any]]] | None:
    candidate = (text or "").strip()
    if not candidate.startswith("{"):
        return None
    try:
        data = json.loads(candidate)
    except (TypeError, ValueError):
        return None
    return extract_blocks_from_structured_resume(data)


def _parse_experience_lines(lines: list[str], *, default_source: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines:
        if _is_new_entry_line(line):
            if current:
                items.append(current)
            title, organization, date_range = _split_title_line(line)
            current = make_block_item(
                title=title,
                organization=organization,
                date_range=date_range,
                source=default_source,
            )
            continue
        if current is None:
            current = make_block_item(description=line, source=default_source)
            continue
        current["description"] = "\n".join(part for part in (current["description"], line) if part)
    if current:
        items.append(current)
    return _drop_empty_items(items)


def _parse_project_lines(lines: list[str], *, default_source: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines:
        normalized_line = _normalize_project_title(line)
        if _SHORT_SKILL_NOISE_RE.match(normalized_line):
            if current and current.get("description"):
                current["description"] = "\n".join(part for part in (current["description"], normalized_line) if part)
            continue
        if _should_merge_into_current_project(current, normalized_line):
            current["description"] = "\n".join(part for part in (current["description"], normalized_line) if part)
            continue
        if _is_new_entry_line(normalized_line) or _looks_like_project_title(normalized_line):
            if current:
                items.append(current)
            date_range = _extract_date_range(normalized_line)
            title = _normalize_project_title(_strip_date_range(normalized_line, date_range))
            current = make_block_item(title=title, date_range=date_range, source=default_source)
            continue
        if current is None:
            current = make_block_item(description=normalized_line, source=default_source)
            continue
        current["description"] = "\n".join(part for part in (current["description"], normalized_line) if part)
    if current:
        items.append(current)
    return _drop_empty_items(_merge_adjacent_project_items(items))


def _parse_education_lines(lines: list[str], *, default_source: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in lines:
        title, organization, date_range = _split_title_line(line)
        items.append(
            make_block_item(
                title=title,
                organization=organization,
                date_range=date_range,
                description=line,
                source=default_source,
            )
        )
    return _drop_empty_items(items)


def _parse_skill_lines(lines: list[str], *, default_source: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in lines:
        cleaned = re.sub(r"^[•·\-*\d.()（）\s]+", "", str(line or "").strip())
        if not cleaned:
            continue
        for token in re.split(r"[、,，/|]", cleaned):
            skill = token.strip()
            if skill:
                items.append(make_block_item(title=skill, source=default_source))
    return _drop_empty_items(items)


def _parse_profile_lines(lines: list[str], *, default_source: str) -> list[dict[str, Any]]:
    return [make_block_item(description=line, source=default_source) for line in lines if line]


def _match_section(line: str) -> str | None:
    lowered = line.lower().strip()
    for block, aliases in _SECTION_ALIASES.items():
        for alias in aliases:
            alias_lower = alias.lower()
            if lowered == alias_lower:
                return block
            if lowered in {alias_lower + ":", alias_lower + "："}:
                return block
    return None


def _clean_line(raw_line: str) -> str:
    line = str(raw_line or "").strip()
    if not line:
        return ""
    if _NOISE_LINE_RE.match(line):
        return ""
    if _NAME_LINE_RE.match(line):
        return ""
    if _CONTACT_RE.search(line):
        return ""
    return re.sub(r"\s+", " ", line).strip()


def _is_new_entry_line(line: str) -> bool:
    if _DATE_RANGE_RE.search(line):
        return True
    if len(line) > 60:
        return False
    return bool(re.search(r"(公司|有限公司|大学|学院|助手|平台|系统|项目|intern|engineer|developer)", line, re.IGNORECASE))


def _looks_like_project_title(line: str) -> bool:
    if len(line) > 40:
        return False
    if any(marker in line.lower() for marker in ("education", "skills", "profile", "summary")):
        return False
    if _AWARD_NOISE_RE.search(line):
        return False
    if _GENERIC_PROJECT_HEADER_RE.match(_normalize_project_title(line)):
        return False
    return bool(re.search(r"(agent|rag|项目|平台|系统|助手|审查|开发|engineer|project)", line, re.IGNORECASE))


def _split_title_line(line: str) -> tuple[str, str, str]:
    date_range = _extract_date_range(line)
    content = _strip_date_range(line, date_range)
    if " " in content:
        left, right = content.split(" ", 1)
        if len(left) <= 20 and len(right) <= 40:
            return right.strip(), left.strip(), date_range.strip()
    return content.strip(), "", date_range.strip()


def _extract_date_range(line: str) -> str:
    date_match = _DATE_RANGE_RE.search(line)
    return date_match.group("date") if date_match else ""


def _strip_date_range(line: str, date_range: str) -> str:
    return line.replace(date_range, "").strip(" -|")


def _join_dates(start_date: Any, end_date: Any) -> str:
    parts = [str(start_date or "").strip(), str(end_date or "").strip()]
    parts = [part for part in parts if part]
    return " - ".join(parts)


def _looks_like_internship(item: dict[str, Any]) -> bool:
    joined = " ".join(
        str(item.get(key) or "")
        for key in ("position", "title", "role", "company", "organization", "details", "description")
    )
    return bool(re.search(r"实习|intern", joined, re.IGNORECASE))


def _drop_empty_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        if any(str(item.get(key) or "").strip() for key in ("title", "organization", "role", "date_range", "description")):
            item["title"] = _normalize_project_title(str(item.get("title") or ""))
            item["description"] = _trim_repeated_description(
                str(item.get("description") or ""),
                str(item.get("title") or ""),
            )
            if item["title"] and not (
                _AWARD_NOISE_RE.search(item["title"])
                or _GENERIC_PROJECT_HEADER_RE.match(item["title"])
                or _SHORT_SKILL_NOISE_RE.match(item["title"])
            ):
                result.append(item)
            elif item["description"] and not _AWARD_NOISE_RE.search(item["description"]):
                result.append(item)
    return result


def _normalize_project_title(value: str) -> str:
    text = re.sub(r"^[★☆•·#\-\d._\s]+", "", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" -|：:")
    return text[:80]


def _should_merge_into_current_project(current: dict[str, Any] | None, line: str) -> bool:
    if not current or not line:
        return False
    if _AWARD_NOISE_RE.search(line):
        return False
    if _is_new_entry_line(line):
        return False
    if _looks_like_project_title(line):
        return False
    return bool(_DESCRIPTIVE_LINE_RE.search(line) or len(line) > 28)


def _merge_adjacent_project_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for item in items:
        if not merged:
            merged.append(item)
            continue
        previous = merged[-1]
        if _can_merge_project_items(previous, item):
            previous["description"] = "\n".join(
                part for part in (previous.get("description", ""), item.get("title", ""), item.get("description", ""))
                if str(part or "").strip()
            )
            continue
        merged.append(item)
    return merged


def _can_merge_project_items(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    prev_title = str(previous.get("title") or "").strip()
    curr_title = str(current.get("title") or "").strip()
    if not prev_title or not curr_title:
        return False
    if prev_title == curr_title:
        return True
    if _GENERIC_PROJECT_HEADER_RE.match(prev_title) and len(curr_title) > len(prev_title):
        previous["title"] = curr_title
        return True
    if len(curr_title) <= 16 and _DESCRIPTIVE_LINE_RE.search(str(current.get("description") or "")):
        return True
    return False


def _trim_repeated_description(description: str, title: str) -> str:
    cleaned = str(description or "").strip()
    normalized_title = str(title or "").strip()
    if normalized_title and cleaned.startswith(normalized_title):
        cleaned = cleaned[len(normalized_title):].strip(" ：:-")
    return cleaned[:320]
