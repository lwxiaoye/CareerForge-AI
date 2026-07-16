import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth.models import StudentUser
from app.auth.router import router as auth_router
from app.infra.db import Base, get_db


class AuthLoginTests(unittest.TestCase):
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

        with self.SessionLocal() as db:
            db.add(
                StudentUser(
                    tenant_id=0,
                    account="student001",
                    email="student001@example.com",
                    password_hash="dummy-hash",
                    name="学生甲",
                    is_deleted=False,
                )
            )
            db.commit()

        app = FastAPI()
        app.include_router(auth_router, prefix="/api/v1")

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_unified_login_accepts_student_account(self):
        with patch("app.auth.service.verify_password", return_value=True):
            resp = self.client.post(
                "/api/v1/auth/login",
                json={"account": "student001", "password": "Abcd1234"},
            )

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["code"], 0)
        self.assertEqual(body["data"]["role"], "student")
        self.assertTrue(body["data"]["access"])
        self.assertTrue(body["data"]["refresh"])


if __name__ == "__main__":
    unittest.main()
