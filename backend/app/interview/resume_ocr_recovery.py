from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.auth.service import AuthIdentity
from app.student.file_text import render_pdf_pages_to_png

OcrParser = Callable[[object, AuthIdentity, list[bytes]], dict[str, Any]]


def build_pdf_ocr_variants(pdf_path: Path, *, exclude_names: set[str] | None = None) -> list[dict[str, object]]:
    variants: list[dict[str, object]] = []
    excluded = exclude_names or set()
    variant_specs = [
        {"name": "first_3_pages_standard", "max_pages": 3, "scale": 2.5},
        {"name": "first_2_pages_hd", "max_pages": 2, "scale": 3.2},
        {"name": "first_4_pages_compact", "max_pages": 4, "scale": 2.1},
    ]

    seen_signatures: set[tuple[int, ...]] = set()
    for spec in variant_specs:
        if spec["name"] in excluded:
            continue
        images = render_pdf_pages_to_png(
            pdf_path,
            max_pages=int(spec["max_pages"]),
            scale=float(spec["scale"]),
        )
        if not images:
            continue
        signature = tuple(len(image) for image in images)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        variants.append(
            {
                "name": spec["name"],
                "page_images": images,
                "max_pages": spec["max_pages"],
                "scale": spec["scale"],
            }
        )
    return variants


def recover_resume_from_pdf_images(
    pdf_path: Path,
    *,
    db: object,
    identity: AuthIdentity,
    parser: OcrParser,
    exclude_names: set[str] | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, object]]]:
    attempts: list[dict[str, object]] = []
    for variant in build_pdf_ocr_variants(pdf_path, exclude_names=exclude_names):
        try:
            parsed = parser(db, identity, list(variant["page_images"]))
            normalized = _unwrap_ocr_payload(parsed)
            if _looks_useful(normalized):
                attempts.append(
                    {
                        "variant": variant["name"],
                        "status": "success",
                        "page_count": len(variant["page_images"]),
                        "scale": variant["scale"],
                        **_extract_ocr_source(parsed),
                    }
                )
                return parsed, attempts
            attempts.append(
                {
                    "variant": variant["name"],
                    "status": "empty_result",
                    "page_count": len(variant["page_images"]),
                    "scale": variant["scale"],
                    **_extract_ocr_source(parsed),
                }
            )
        except Exception as exc:
            attempts.append(
                {
                    "variant": variant["name"],
                    "status": "error",
                    "page_count": len(variant["page_images"]),
                    "scale": variant["scale"],
                    "error": str(exc)[:160],
                }
            )
    return None, attempts


def _unwrap_ocr_payload(parsed: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(parsed, dict):
        return None
    data = parsed.get("data")
    if isinstance(data, dict):
        return data
    return parsed


def _extract_ocr_source(parsed: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        return {}
    source = parsed.get("source")
    return dict(source) if isinstance(source, dict) else {}


def _looks_useful(parsed: dict | None) -> bool:
    parsed = _unwrap_ocr_payload(parsed)
    if not isinstance(parsed, dict):
        return False
    if parsed.get("projects") or parsed.get("experience"):
        return True
    skills = parsed.get("skills")
    if isinstance(skills, str) and skills.strip():
        return True
    education = parsed.get("education")
    if isinstance(education, list) and len(education) >= 2:
        return True
    return False
