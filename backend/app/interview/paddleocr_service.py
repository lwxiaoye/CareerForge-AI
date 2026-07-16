from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from typing import Any

from app.core.config import get_settings


@dataclass
class PaddleOcrResult:
    provider: str
    status: str
    text: str
    pages: int
    error: str | None = None


def run_paddleocr_on_pdf_pages(
    page_images: list[bytes],
    *,
    force_unavailable: bool = False,
) -> PaddleOcrResult:
    settings = get_settings()
    if force_unavailable:
        return PaddleOcrResult(
            provider="paddleocr_local",
            status="unavailable",
            text="",
            pages=len(page_images),
            error="forced_unavailable",
        )
    if not settings.interview_use_local_paddleocr:
        return PaddleOcrResult(
            provider="paddleocr_local",
            status="disabled",
            text="",
            pages=len(page_images),
            error="local_ocr_disabled",
        )
    if not page_images:
        return PaddleOcrResult(
            provider="paddleocr_local",
            status="empty_result",
            text="",
            pages=0,
            error="no_page_images",
        )

    try:
        ocr_engine = _get_paddleocr_engine(settings.interview_local_paddleocr_lang)
    except Exception as exc:  # pragma: no cover - exercised via unavailable path
        return PaddleOcrResult(
            provider="paddleocr_local",
            status="unavailable",
            text="",
            pages=len(page_images),
            error=str(exc)[:200],
        )

    page_texts: list[str] = []
    try:
        from PIL import Image
        import numpy as np
    except Exception as exc:  # pragma: no cover - runtime dependency issue
        return PaddleOcrResult(
            provider="paddleocr_local",
            status="unavailable",
            text="",
            pages=len(page_images),
            error=f"runtime dependency missing: {str(exc)[:160]}",
        )

    for index, raw_image in enumerate(page_images, start=1):
        try:
            image = Image.open(BytesIO(raw_image)).convert("RGB")
            result = ocr_engine.ocr(np.array(image), cls=True)
            page_text = _extract_text_from_paddle_result(result)
            if page_text:
                page_texts.append(f"[OCR Page {index}]\n{page_text}")
        except Exception as exc:
            if not page_texts:
                return PaddleOcrResult(
                    provider="paddleocr_local",
                    status="error",
                    text="",
                    pages=len(page_images),
                    error=str(exc)[:200],
                )

    text = "\n\n".join(page_texts).strip()
    return PaddleOcrResult(
        provider="paddleocr_local",
        status="success" if text else "empty_result",
        text=text,
        pages=len(page_images),
        error=None if text else "no_text_extracted",
    )


def warm_paddleocr_engine() -> str:
    settings = get_settings()
    if not settings.interview_use_local_paddleocr:
        return "disabled"
    try:
        _get_paddleocr_engine(settings.interview_local_paddleocr_lang)
    except Exception:
        return "unavailable"
    return "ready"


@lru_cache(maxsize=2)
def _get_paddleocr_engine(lang: str):
    try:
        from paddleocr import PaddleOCR
    except Exception as exc:  # pragma: no cover - depends on local install
        raise RuntimeError(f"paddleocr import failed: {str(exc)[:160]}") from exc
    return PaddleOCR(use_angle_cls=True, lang=lang)


def _extract_text_from_paddle_result(result: Any) -> str:
    lines: list[str] = []
    for page in result or []:
        if not isinstance(page, list):
            continue
        for item in page:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            payload = item[1]
            if isinstance(payload, (list, tuple)) and payload:
                text = str(payload[0] or "").strip()
                if text:
                    lines.append(text)
    return "\n".join(lines).strip()
