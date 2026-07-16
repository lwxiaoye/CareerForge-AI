import asyncio
import io
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi import UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin.models import ModelConfig
from app.auth.service import AuthIdentity
from app.core.security import create_access_token
from app.infra.db import Base, get_db
from app.auth.models import StudentUser
from app.interview.router_student import router as interview_student_router
from app.interview.service import (
    _build_conservative_opening_question,
    _extract_resume_anchor_payload,
    _extract_resume_anchors,
    _is_direct_question_anchor,
    _select_opening_anchor,
    extract_uploaded_resume,
)


class UploadedResumeExtractionTests(unittest.TestCase):
    def _make_upload(self, filename: str, content: bytes, content_type: str) -> UploadFile:
        return UploadFile(
            file=io.BytesIO(content),
            filename=filename,
            headers={"content-type": content_type},
        )

    def _make_identity(self) -> AuthIdentity:
        return AuthIdentity(user_id=1, tenant_id=0, role="student")

    def test_extract_uploaded_resume_prefers_structured_project_over_pdf_noise(self):
        noisy_text = "\n".join([
            "[PDF ? 1 ?]",
            "Name: Leo Liang",
            "Education",
            "Chongqing Institute of Engineering Software Engineering Bachelor 2023/09 - 2027/06",
            "Contract Review Assistant AI Contract Risk Review 2026/01 - 2026/03",
        ])
        parsed_resume = {
            "basic": {"name": "Leo Liang"},
            "education": [
                {
                    "school": "Chongqing Institute of Engineering",
                    "major": "Software Engineering",
                    "degree": "Bachelor",
                    "start_date": "2023-09-01",
                    "end_date": "2027-06-01",
                    "description": "",
                }
            ],
            "experience": [],
            "projects": [
                {
                    "name": "Contract Review Assistant",
                    "role": "AI Application Engineer Intern",
                    "date": "2026/01 - 2026/03",
                    "description": "Owned contract risk review workflow, RAG retrieval, and result rendering",
                }
            ],
            "skills": "Agent\nRAG\nGPT",
            "self_evaluation": "",
        }

        with patch("app.interview.service.extract_resume_file", return_value=noisy_text), \
             patch("app.interview.service.parse_resume_text_to_data", return_value=parsed_resume):
            result = asyncio.run(
                extract_uploaded_resume(
                    self._make_upload("resume.pdf", b"%PDF-1.4 fake", "application/pdf"),
                    db=MagicMock(),
                    identity=self._make_identity(),
                )
            )

        extracted_text = result["extracted_text"]
        self.assertIn("Contract Review Assistant", extracted_text)
        self.assertIn("RAG", extracted_text)
        self.assertNotIn("[PDF", extracted_text)
        self.assertNotIn("Name:", extracted_text)

    def test_extracted_resume_text_leads_to_project_opening_anchor(self):
        noisy_text = "\n".join([
            "[PDF ? 1 ?]",
            "Name: Leo Wu",
            "Education",
            "Chongqing Institute of Engineering Software Engineering Bachelor 2023/09 - 2027/06",
            "Contract Review Assistant AI Contract Risk Review 2026/01 - 2026/03",
        ])
        parsed_resume = {
            "basic": {"name": "Leo Wu"},
            "education": [],
            "experience": [],
            "projects": [
                {
                    "name": "Contract Review Assistant",
                    "role": "AI Application Engineer",
                    "date": "2026/01 - 2026/03",
                    "description": "Implemented clause extraction and risk highlighting",
                }
            ],
            "skills": "Agent\nRAG",
            "self_evaluation": "",
        }

        with patch("app.interview.service.extract_resume_file", return_value=noisy_text), \
             patch("app.interview.service.parse_resume_text_to_data", return_value=parsed_resume):
            result = asyncio.run(
                extract_uploaded_resume(
                    self._make_upload("resume.pdf", b"%PDF-1.4 fake", "application/pdf"),
                    db=MagicMock(),
                    identity=self._make_identity(),
                )
            )

        anchors = _extract_resume_anchors(result["extracted_text"])
        opening_anchor = _select_opening_anchor(anchors)
        self.assertIsNotNone(opening_anchor)
        self.assertIn("Contract Review Assistant", opening_anchor.get("name", ""))

    def test_extract_resume_anchor_payload_prefers_project_over_education(self):
        parsed_resume = {
            "basic": {"name": "Leo Wu"},
            "education": [
                {
                    "school": "Chongqing Institute of Engineering",
                    "major": "Software Engineering",
                    "degree": "Bachelor",
                    "start_date": "2023-09-01",
                    "end_date": "2027-06-01",
                    "description": "",
                }
            ],
            "experience": [],
            "projects": [
                {
                    "name": "Contract Review Assistant",
                    "role": "AI Application Engineer",
                    "date": "2026/01 - 2026/03",
                    "description": "Implemented clause extraction and risk highlighting",
                }
            ],
            "skills": "Agent\nRAG",
            "self_evaluation": "",
        }

        payload = _extract_resume_anchor_payload(
            "Education\nChongqing Institute of Engineering\nContract Review Assistant AI Contract Risk Review 2026/01 - 2026/03",
            structured_resume=parsed_resume,
        )

        self.assertEqual(payload["best_opening_anchor"]["type"], "project")
        self.assertIn("Contract Review Assistant", payload["best_opening_anchor"]["name"])
        self.assertTrue(payload["resume_blocks"]["education"])
        self.assertTrue(payload["resume_blocks"]["projects"])

    def test_extract_uploaded_resume_falls_back_to_sanitized_text_when_structured_parse_fails(self):
        noisy_text = "\n".join([
            "[PDF ? 1 ?]",
            "Name: Leo Wu",
            "Education",
            "Contract Review Assistant AI Contract Risk Review 2026/01 - 2026/03",
            "Built a RAG workflow for clause retrieval",
        ])

        with patch("app.interview.service.extract_resume_file", return_value=noisy_text), \
             patch("app.interview.service.parse_resume_text_to_data", side_effect=RuntimeError("boom")):
            result = asyncio.run(
                extract_uploaded_resume(
                    self._make_upload("resume.pdf", b"%PDF-1.4 fake", "application/pdf"),
                    db=MagicMock(),
                    identity=self._make_identity(),
                )
            )

        extracted_text = result["extracted_text"]
        self.assertIn("Contract Review Assistant", extracted_text)
        self.assertIn("Built a RAG workflow", extracted_text)
        self.assertNotIn("[PDF", extracted_text)
        self.assertNotIn("Name:", extracted_text)

    def test_extract_uploaded_resume_prefers_local_ocr_before_text_fallback(self):
        mock_provider = MagicMock()
        mock_provider.name = "paddleocr_local"
        mock_provider.parse.return_value = {
            "text": "\n".join([
                "CareerForge-AI",
                "Built a RAG workflow for clause retrieval",
            ]),
            "source": {
                "provider": "paddleocr_local",
                "model_name": "PaddleOCR Local",
                "model_identifier": "paddleocr-local",
                "capability": "ocr",
                "status": "success",
                "pages": 1,
            },
        }

        with patch("app.interview.service.extract_resume_file", return_value="plain fallback text should not win"), \
             patch("app.interview.service.render_pdf_pages_to_png", return_value=[b"page-a"]), \
             patch("app.interview.service.get_default_resume_ocr_provider", return_value=mock_provider), \
             patch("app.interview.service.parse_resume_text_to_data") as parse_mock:
            result = asyncio.run(
                extract_uploaded_resume(
                    self._make_upload("resume.pdf", b"%PDF-1.4 fake", "application/pdf"),
                    db=MagicMock(),
                    identity=self._make_identity(),
                )
            )

        self.assertIn("CareerForge-AI", result["extracted_text"])
        self.assertNotIn("plain fallback text should not win", result["extracted_text"])
        self.assertTrue(result["ocr_attempts"])
        self.assertEqual(result["ocr_attempts"][0]["variant"], "local_paddleocr_page_1")
        self.assertEqual(result["ocr_attempts"][0]["status"], "success")
        parse_mock.assert_not_called()

    def test_extract_uploaded_resume_includes_ocr_model_source(self):
        mock_provider = MagicMock()
        mock_provider.name = "paddleocr_local"
        mock_provider.parse.return_value = {
            "text": "CareerForge-AI\nBuilt resume anchor extraction flow",
            "source": {
                "provider": "paddleocr_local",
                "model_name": "PaddleOCR Local",
                "model_identifier": "paddleocr-local",
                "capability": "ocr",
                "status": "success",
            },
        }

        with patch("app.interview.service.extract_resume_file", return_value=""), \
             patch("app.interview.service.render_pdf_pages_to_png", return_value=[b"page-a"]), \
             patch("app.interview.service.get_default_resume_ocr_provider", return_value=mock_provider):
            result = asyncio.run(
                extract_uploaded_resume(
                    self._make_upload("resume.pdf", b"%PDF-1.4 fake", "application/pdf"),
                    db=MagicMock(),
                    identity=self._make_identity(),
                )
            )

        self.assertEqual(result["ocr_attempts"][0]["provider"], "paddleocr_local")
        self.assertEqual(result["ocr_attempts"][0]["model_name"], "PaddleOCR Local")
        self.assertEqual(result["ocr_attempts"][0]["model_identifier"], "paddleocr-local")
        self.assertEqual(result["ocr_attempts"][0]["capability"], "ocr")

    def test_extract_uploaded_resume_expands_from_first_page_to_three_pages_only_when_needed(self):
        short_ocr = {
            "parsed_data": None,
            "text": "short note",
            "ocr_attempts": [{"variant": "local_paddleocr_standard", "status": "success"}],
        }
        full_ocr = {
            "parsed_data": None,
            "text": "\n".join([
                "CareerForge-AI",
                "Built a RAG workflow for clause retrieval",
                "Designed prompt injection pipeline",
                "Improved interview question grounding",
            ]),
            "ocr_attempts": [{"variant": "local_paddleocr_standard", "status": "success"}],
        }

        with patch("app.interview.service.render_pdf_pages_to_png", side_effect=[[b"page-1"], [b"page-1", b"page-2", b"page-3"]]) as render_mock, \
             patch("app.interview.service._run_local_pdf_ocr_first", side_effect=[short_ocr, full_ocr]), \
             patch("app.interview.service.extract_resume_file", return_value=""), \
             patch("app.interview.service.parse_resume_text_to_data") as parse_mock:
            result = asyncio.run(
                extract_uploaded_resume(
                    self._make_upload("resume.pdf", b"%PDF-1.4 fake", "application/pdf"),
                    db=MagicMock(),
                    identity=self._make_identity(),
                )
            )

        self.assertIn("CareerForge-AI", result["extracted_text"])
        self.assertEqual(render_mock.call_args_list[0].kwargs["max_pages"], 1)
        self.assertEqual(render_mock.call_args_list[1].kwargs["max_pages"], 3)
        self.assertEqual(result["ocr_attempts"][0]["variant"], "local_paddleocr_page_1")
        self.assertEqual(result["ocr_attempts"][1]["variant"], "local_paddleocr_page_1_to_3")
        parse_mock.assert_not_called()

    def test_fragment_like_anchor_uses_conservative_opening_question(self):
        fragment_anchor = {
            "name": "效率开发，具备较强的 AI 协",
            "type": "project",
            "evidence": "效率开发，具备较强的 AI 协",
            "source_block": "projects",
        }

        self.assertFalse(_is_direct_question_anchor(fragment_anchor))
        question = _build_conservative_opening_question(
            opening_anchor=fragment_anchor,
            resume_source_label="本次上传简历",
            target_role="AI Agent 开发工程师",
        )

        self.assertIn("你简历里提到了一段与", question)
        self.assertIn("AI", question)
        self.assertNotIn("效率开发，具备较强的 AI 协", question)

    def test_extract_resume_anchor_payload_uses_fallback_after_four_attempts(self):
        payload = _extract_resume_anchor_payload(
            "\n".join([
                "[PDF ? 1 ?]",
                "Name: Leo Wu",
                "Education",
                "Chongqing Institute of Engineering",
                "Software Engineering",
            ])
        )

        self.assertIsNone(payload["best_opening_anchor"])
        self.assertTrue(str(payload["fallback_reason"]).startswith("resume_anchor_extraction_failed"))
        self.assertEqual(len(payload["attempts"]), 4)
        self.assertEqual(payload["attempts"][-1]["failure_reason"], "only_education_detected")

    def test_extract_resume_anchor_payload_repairs_unlabeled_internship_first(self):
        payload = _extract_resume_anchor_payload(
            "\n".join([
                "Leo Wu",
                "Mianyang Jianghua Wood Co., Ltd. AI Application Engineer Intern 2026/03 - Present",
                "Responsible for Agent application delivery and workflow review",
                "Contract Review Assistant AI Contract Risk Review 2026/01 - 2026/03",
                "Built a RAG workflow for clause retrieval",
            ])
        )

        self.assertIsNotNone(payload["best_opening_anchor"])
        self.assertEqual(payload["best_opening_anchor"]["type"], "internship")
        self.assertIn("Intern", payload["best_opening_anchor"]["name"])
        self.assertEqual(payload["attempts"][-1]["failure_reason"], "recovered")


class UploadedResumeExtractRouteTests(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db_path = path
        self.engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False}, future=True)
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False, future=True)
        Base.metadata.create_all(self.engine)

        with self.SessionLocal() as db:
            db.add(
                StudentUser(
                    id=1,
                    tenant_id=0,
                    account="student-a",
                    email="student-a@example.com",
                    password_hash="x",
                    name="Student A",
                    is_deleted=False,
                )
            )
            db.add(
                ModelConfig(
                    tenant_id=0,
                    display_name="OCR Resume Reader",
                    provider="OpenAI",
                    deploy_type="cloud",
                    capability="ocr",
                    protocols="openai",
                    base_url="https://api.example.com/v1",
                    api_key_cipher="cipher",
                    model_identifier="ocr-resume-reader",
                    open_to_student=True,
                    status="active",
                    is_deleted=False,
                )
            )
            db.add(
                ModelConfig(
                    tenant_id=0,
                    display_name="Generic Multimodal Chat",
                    provider="OpenAI",
                    deploy_type="cloud",
                    capability="multimodal",
                    protocols="openai",
                    base_url="https://api.example.com/v1",
                    api_key_cipher="cipher",
                    model_identifier="generic-mm-chat",
                    open_to_student=True,
                    status="active",
                    is_deleted=False,
                )
            )
            db.commit()

        app = FastAPI()
        app.include_router(interview_student_router, prefix="/api/v1")

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.token = create_access_token(sub="1", role="student", tenant_id=0)

    def tearDown(self):
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def test_resume_extract_endpoint_returns_clean_text(self):
        parsed_resume = {
            "basic": {"name": "Leo Liang"},
            "education": [],
            "experience": [],
            "projects": [
                {
                    "name": "Contract Review Assistant",
                    "role": "AI Application Engineer Intern",
                    "date": "2026/01 - 2026/03",
                    "description": "Owned contract risk review workflow and RAG retrieval",
                }
            ],
            "skills": "Agent\nRAG",
            "self_evaluation": "",
        }

        extracted_text = "\n".join([
            "[PDF ? 1 ?]",
            "Name: Leo Liang",
            "Contract Review Assistant AI Contract Risk Review 2026/01 - 2026/03",
            "Owned contract risk review workflow and RAG retrieval",
        ])

        with patch("app.interview.service.extract_resume_file", return_value=extracted_text), \
             patch("app.interview.service.parse_resume_text_to_data", return_value=parsed_resume):
            response = self.client.post(
                "/api/v1/student/interviews/resume/extract",
                headers=self._headers(),
                files={"file": ("resume.pdf", b"%PDF-1.4 fake", "application/pdf")},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertIn("Contract Review Assistant", payload["extracted_text"])
        self.assertNotIn("[PDF", payload["extracted_text"])
        self.assertIn("resume_blocks", payload)
        self.assertIn("anchors", payload)
        self.assertIn("best_opening_anchor", payload)
        self.assertIn("projects", payload["resume_blocks"])

    def test_resume_extract_endpoint_reports_ocr_model_source(self):
        parsed_resume = {
            "basic": {"name": "Leo Liang"},
            "education": [],
            "experience": [],
            "projects": [
                {
                    "name": "Contract Review Assistant",
                    "role": "AI Application Engineer Intern",
                    "date": "2026/01 - 2026/03",
                    "description": "Owned contract risk review workflow and RAG retrieval",
                }
            ],
            "skills": "Agent\nRAG",
            "self_evaluation": "",
        }
        mock_provider = MagicMock()
        mock_provider.name = "ocr_model"
        mock_provider.parse.return_value = {
            "data": parsed_resume,
            "source": {
                "provider": "OpenAI",
                "model_id": 1,
                "model_name": "OCR Resume Reader",
                "model_identifier": "ocr-resume-reader",
                "capability": "ocr",
            },
        }

        with patch("app.interview.service.extract_resume_file", return_value=""), \
             patch("app.interview.service.render_pdf_pages_to_png", return_value=[b"page-a"]), \
             patch("app.interview.service.get_default_resume_ocr_provider", return_value=mock_provider):
            response = self.client.post(
                "/api/v1/student/interviews/resume/extract",
                headers=self._headers(),
                files={"file": ("resume.pdf", b"%PDF-1.4 fake", "application/pdf")},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["ocr_attempts"][0]["capability"], "ocr")
        self.assertEqual(payload["ocr_attempts"][0]["model_name"], "OCR Resume Reader")
