# Resume Anchor Sample Review

This file is the human-readable acceptance sheet for the sanitized regression samples in `index.json`.

How to use it:
- Read one sample at a time.
- Judge it from the interviewer experience, not from parser internals.
- If the "correct first question target" feels wrong in plain language, the sample should be fixed before it enters regression.

## Review Standard

For every sample, we want the first question to land on the strongest real evidence in this order:

1. Work experience
2. Internship experience
3. Project experience
4. Education only when it contains a real thesis / competition / course project and nothing stronger exists
5. Never pure title noise, name lines, school-only lines, short skill labels, or award-only lines

## Sample Catalog

| Sample ID | Template Type | Correct First Question Target | Why This Is Correct | Must Not Be Chosen |
| --- | --- | --- | --- | --- |
| `contract-review-project` | Project-first | `合同审查助手` | This sample has no work or internship signal. The project has a name, date range, and concrete responsibilities, so it is the strongest interview entry point. | `教育经历`, `重庆工程学院` |
| `unlabeled-internship-and-project` | Unlabeled mixed | `绵阳江花木业有限公司 AI 应用工程师实习生` | The resume does not explicitly label sections, so the parser must still recognize that a dated company-role line outranks the following project. | `梁伟业` |
| `work-experience-before-project` | Work-first | `上海某科技有限公司 后端开发工程师` | Real work experience should always outrank a side project when both are present and readable. | `工作经历` |
| `compact-project-title-template` | Compact title template | `03_Agent工程化与生产实践` | This template mixes compact headings with sparse content. We still want the parser to pick the most project-like item instead of the section title or a short skill word. | `项目经历 Experience`, `RAG` |
| `template-noise-title-should-not-win` | Template-noise heavy | `CareerForge-AI` | The leading `★ AI 增强开发` is a template-style summary heading, not a real project. The dated project line is the real interview anchor. | `★ AI 增强开发`, `院级奖项10次` |

## Quick Manual Check

A sample is acceptable only if all of the following are true:

- A non-technical reviewer can point to the same first-question target in under 30 seconds.
- The target is a real project / internship / work item that a candidate can meaningfully explain.
- The forbidden items are obviously weaker than the chosen target.
- If the parser selected one of the forbidden items instead, the interviewer experience would clearly feel wrong.
