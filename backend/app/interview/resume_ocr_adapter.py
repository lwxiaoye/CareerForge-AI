from __future__ import annotations

from typing import Any, Protocol

from app.auth.service import AuthIdentity
from app.interview.paddleocr_service import run_paddleocr_on_pdf_pages


class ResumeOcrProvider(Protocol):
    name: str

    def parse(self, db: object, identity: AuthIdentity, page_images: list[bytes]) -> dict[str, Any]:
        ...


class LocalPaddleResumeOcrProvider:
    name = "paddleocr_local"

    def parse(self, db: object, identity: AuthIdentity, page_images: list[bytes]) -> dict[str, Any]:
        result = run_paddleocr_on_pdf_pages(page_images)
        return {
            "text": result.text,
            "source": {
                "provider": result.provider,
                "model_name": "PaddleOCR Local",
                "model_identifier": "paddleocr-local",
                "capability": "ocr",
                "status": result.status,
                "pages": result.pages,
                "error": result.error,
            },
        }


def get_default_resume_ocr_provider() -> ResumeOcrProvider:
    return LocalPaddleResumeOcrProvider()
