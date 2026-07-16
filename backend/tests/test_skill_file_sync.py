import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.infra.db import Base
from app.skills.service import list_skills


class SkillFileSyncTests(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db_path = path
        self.engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False}, future=True)
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False, future=True)
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_list_skills_imports_file_backed_skill_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "paddleocr-resume-extraction")
            os.makedirs(skill_dir, exist_ok=True)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write(
                    "\n".join(
                        [
                            "---",
                            "name: PaddleOCR 简历识别",
                            "description: PDF OCR first",
                            "version: 1.0.0",
                            "category: 面试官",
                            "tags: OCR, 简历解析",
                            "---",
                            "",
                            "# PaddleOCR 简历识别",
                        ]
                    )
                )

            settings = SimpleNamespace(skill_storage_dir=tmpdir)
            with self.SessionLocal() as db, patch("app.skills.service.get_settings", return_value=settings):
                skills = list_skills(db)

            self.assertEqual(len(skills), 1)
            self.assertEqual(skills[0].slug, "paddleocr-resume-extraction")
            self.assertEqual(skills[0].name, "PaddleOCR 简历识别")
            self.assertEqual(skills[0].category, "面试官")

