This directory stores sanitized resume-anchor regression samples.

Contract:
- `index.json` is the entry point.
- Each sample declares the expected `best_opening_anchor_type`.
- We use these fixtures to prevent regressions such as picking `Education`, `姓名`, or short skill tags as the first interview question anchor.
- Human review notes live in `SAMPLE_REVIEW.md`.

Recommended expansion fields per sample:
- `id`
- `category`
- `source_type`
- `resume_text`
- `expected_best_opening_anchor`
- `expected_best_opening_anchor_type`
- `expected_must_include_keywords`
- `expected_must_exclude_keywords`

Suggested category values:
- `project_first`
- `work_first`
- `unlabeled_mixed`
- `compact_project_title`
- `education_heavy_noise`
- `scanned_pdf_like`

Review workflow:
1. Read the sanitized sample text and decide the best first-question target in business terms.
2. Confirm the anchor is a real work / internship / project item, not education, name, title noise, or a short skill tag.
3. Record the human-readable judgment in `SAMPLE_REVIEW.md`.
4. Encode the machine assertions in `index.json`.
5. Run:
   `python -m pytest tests/test_resume_anchor_dataset_contract.py -v`

Acceptance checklist for each sample:
- The first question must not land on education.
- The first question must not land on a person's name.
- The first question must not land on a template heading or award line.
- Work experience outranks internship, internship outranks project, and project outranks generic skill labels.
- Project blocks should stay reasonably merged instead of exploding into many fragments.
