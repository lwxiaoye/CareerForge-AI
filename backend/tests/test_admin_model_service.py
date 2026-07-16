import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin.model_service import _api_protocol, test_model_connection
from app.admin.models import ModelConfig
from app.infra.db import Base


class AdminModelServiceTests(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db_path = path
        self.engine = create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False,
            future=True,
        )
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_api_protocol_detects_baidu_ocr(self):
        model = ModelConfig(
            tenant_id=0,
            display_name="Baidu OCR",
            provider="Baidu",
            deploy_type="cloud",
            capability="ocr",
            protocols="baidu_ocr",
            base_url="https://aip.baidubce.com",
            model_identifier="general_basic",
            open_to_student=False,
            status="active",
            is_deleted=False,
        )

        self.assertEqual(_api_protocol(model), "baidu_ocr")

    def test_test_model_connection_uses_baidu_ocr_parameters(self):
        with self.SessionLocal() as db:
            db.add(
                ModelConfig(
                    tenant_id=0,
                    display_name="Baidu OCR",
                    provider="Baidu",
                    deploy_type="cloud",
                    capability="ocr",
                    protocols="baidu_ocr",
                    base_url="https://aip.baidubce.com",
                    api_key_cipher="cipher",
                    model_identifier="general_basic",
                    open_to_student=False,
                    status="active",
                    is_deleted=False,
                )
            )
            db.commit()
            model_id = db.query(ModelConfig).first().id

        captured: dict[str, object] = {}

        class _FakeResp:
            def __init__(self, *, status_code: int, json_body: dict, text: str):
                self.status_code = status_code
                self._json_body = json_body
                self.text = text
                self.reason_phrase = "OK" if status_code < 400 else "Bad Request"
                self.request = object()

            @property
            def is_success(self) -> bool:
                return 200 <= self.status_code < 300

            def json(self):
                return self._json_body

            def raise_for_status(self):
                if not self.is_success:
                    raise RuntimeError(self.text)

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, url, params=None, **kwargs):
                captured["token_url"] = url
                captured["token_params"] = params
                return _FakeResp(
                    status_code=200,
                    json_body={"access_token": "baidu-token"},
                    text='{"access_token":"baidu-token"}',
                )

            async def post(self, url, headers=None, data=None, **kwargs):
                captured["ocr_url"] = url
                captured["ocr_headers"] = headers
                captured["ocr_data"] = data
                return _FakeResp(
                    status_code=200,
                    json_body={"words_result": [{"words": "梁伟业"}]},
                    text='{"words_result":[{"words":"梁伟业"}]}',
                )

        with self.SessionLocal() as db, \
             patch("app.admin.model_service.decrypt_api_key", return_value="baidu-ak|baidu-sk"), \
             patch("app.admin.model_service.httpx.AsyncClient", _FakeClient):
            result = asyncio.run(test_model_connection(db, model_id))

        self.assertTrue(result.success)
        self.assertIn("/oauth/2.0/token", captured["token_url"])
        self.assertEqual(
            captured["token_params"],
            {
                "grant_type": "client_credentials",
                "client_id": "baidu-ak",
                "client_secret": "baidu-sk",
            },
        )
        self.assertIn("/rest/2.0/ocr/v1/general_basic?access_token=baidu-token", captured["ocr_url"])
        self.assertEqual(
            captured["ocr_headers"]["Content-Type"],
            "application/x-www-form-urlencoded",
        )
        self.assertIn("image", captured["ocr_data"])


if __name__ == "__main__":
    unittest.main()
