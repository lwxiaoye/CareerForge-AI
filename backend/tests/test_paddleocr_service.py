import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.interview.paddleocr_service import warm_paddleocr_engine


class PaddleOcrWarmupTests(unittest.TestCase):
    def test_warm_paddleocr_engine_returns_disabled_when_local_ocr_is_off(self):
        settings = SimpleNamespace(
            interview_use_local_paddleocr=False,
            interview_local_paddleocr_lang="ch",
        )
        with patch("app.interview.paddleocr_service.get_settings", return_value=settings):
            self.assertEqual(warm_paddleocr_engine(), "disabled")

    def test_warm_paddleocr_engine_returns_ready_after_successful_init(self):
        settings = SimpleNamespace(
            interview_use_local_paddleocr=True,
            interview_local_paddleocr_lang="ch",
        )
        with patch("app.interview.paddleocr_service.get_settings", return_value=settings), \
             patch("app.interview.paddleocr_service._get_paddleocr_engine", return_value=object()) as engine_mock:
            self.assertEqual(warm_paddleocr_engine(), "ready")
        engine_mock.assert_called_once_with("ch")

    def test_warm_paddleocr_engine_returns_unavailable_on_init_error(self):
        settings = SimpleNamespace(
            interview_use_local_paddleocr=True,
            interview_local_paddleocr_lang="ch",
        )
        with patch("app.interview.paddleocr_service.get_settings", return_value=settings), \
             patch("app.interview.paddleocr_service._get_paddleocr_engine", side_effect=RuntimeError("boom")):
            self.assertEqual(warm_paddleocr_engine(), "unavailable")

