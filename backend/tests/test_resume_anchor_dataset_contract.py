import json
from pathlib import Path
import unittest

from app.interview.resume_anchor_loop import extract_resume_analysis


class ResumeAnchorDatasetContractTests(unittest.TestCase):
    def test_method_template_noise_is_not_project_anchor(self):
        resume_text = "\n".join([
            "结合 Harness Engineering 与 Function Calling 约束审查链路、'AI 增强开发、Antigravity 等 AI 编程工具进行高效率开发",
            "项目复盘等场景 Prompt 模板、多 Agent 审查",
        ])

        payload = extract_resume_analysis(resume_text)

        self.assertEqual(payload["anchors"], [])
        self.assertIsNone(payload["best_opening_anchor"])
        self.assertIn("resume_anchor_extraction_failed", payload["fallback_reason"])

    def test_dataset_contract_and_anchor_expectations(self):
        fixture_path = Path(__file__).parent / "fixtures" / "resume_anchor_samples" / "index.json"
        samples = json.loads(fixture_path.read_text(encoding="utf-8"))

        self.assertIsInstance(samples, list)
        self.assertGreaterEqual(len(samples), 1)

        for sample in samples:
            self.assertIn("category", sample)
            self.assertIn("resume_text", sample)
            self.assertIn("expected_best_opening_anchor_type", sample)

            payload = extract_resume_analysis(sample["resume_text"])
            best_anchor = payload["best_opening_anchor"]

            self.assertIsNotNone(best_anchor, sample["id"])
            self.assertEqual(best_anchor["type"], sample["expected_best_opening_anchor_type"], sample["id"])

            joined = " ".join(anchor.get("name", "") for anchor in payload["anchors"])
            for keyword in sample.get("expected_must_include_keywords", []):
                self.assertIn(keyword, joined, sample["id"])
            for keyword in sample.get("expected_must_exclude_keywords", []):
                self.assertNotIn(keyword, joined, sample["id"])

            expected_fallback_reason = sample.get("expected_fallback_reason")
            if expected_fallback_reason is not None:
                self.assertEqual(payload["fallback_reason"], expected_fallback_reason, sample["id"])

            max_project_blocks = sample.get("max_project_blocks")
            if max_project_blocks is not None:
                self.assertLessEqual(
                    len(payload["resume_blocks"]["projects"]),
                    int(max_project_blocks),
                    sample["id"],
                )


if __name__ == "__main__":
    unittest.main()
