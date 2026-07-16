import { expect, test } from '@playwright/test'

const ok = (data: unknown) => ({ code: 0, msg: 'ok', data })

async function mockStudentApi(page: import('@playwright/test').Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('zhipei-auth-session', JSON.stringify({
      access: 'test-access',
      refresh: 'test-refresh',
      role: 'student',
      profile: { id: 100, nickname: 'E2E Student' },
    }))
  })

  await page.route('**/api/v1/auth/me', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(ok({ role: 'student', profile: { id: 100, nickname: 'E2E Student' } })),
    })
  })
  await page.route('**/api/v1/student/interviews/knowledge/status', async (route) => {
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(ok({ document_count: 1, chunk_count: 4, retriever: 'mock', vector_ready: true })) })
  })
  await page.route('**/api/v1/student/master/models', async (route) => {
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(ok([{ id: 1, display_name: 'Mock Interviewer', provider: 'mock', model_identifier: 'mock-v1' }])) })
  })
  await page.route('**/api/v1/student/resumes', async (route) => {
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(ok([
      { id: 9, title: '梁伟业简历_java开发.pdf', updated_at: '2026-06-15T00:00:00Z' },
      { id: 10, title: 'Agent开发实习生简历', updated_at: '2026-06-14T00:00:00Z' },
    ])) })
  })
  await page.route('**/api/v1/student/interviews', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(ok([])) })
      return
    }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(ok({
      session: { id: 1, target_role: '后端工程师', interview_type: 'first_round', interview_style: 'strict', difficulty: 'normal', round_limit: 8, status: 'active' },
      first_turn: { id: 11, turn_index: 1, question: '请介绍你最熟悉的一个后端项目。', answer: null },
      knowledge_status: { document_count: 1, chunk_count: 4, retriever: 'mock', vector_ready: true },
    })) })
  })
  await page.route('**/api/v1/student/interviews/runs/start', async (route) => {
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(ok({ run_id: 'run-1', request_id: 'req-1' })) })
  })
  await page.route('**/api/v1/student/interviews/runs/run-1/events?**', async (route) => {
    const body = [
      'event: interview.stage.started',
      'data: {"seq":1,"stage":"resume","title":"读取在线简历"}',
      '',
      'event: done',
      'data: {"seq":2}',
      '',
      '',
    ].join('\n')
    await route.fulfill({ contentType: 'text/event-stream', body })
  })
}

test('AI interviewer shows a progress bar while preparing interview', async ({ page }) => {
  await mockStudentApi(page)
  await page.goto('/student/interviewer')

  await expect(page.locator('.interview-page')).toBeVisible()
  await page.getByPlaceholder(/Java/).fill('后端工程师')
  await page.getByPlaceholder(/JD/).fill('负责 Java、Redis、MySQL、系统设计和线上稳定性。')
  await page.locator('.interview-config-panel button.arco-btn-primary').last().click()

  await expect(page.locator('.interview-progress-bar')).toBeVisible()
  await expect(page.locator('.interview-progress-bar-fill')).toHaveAttribute('style', /width:/)
})

test('audio mime picker falls back to a supported recording type', async ({ page }) => {
  await page.goto('/student/interviewer')
  const selected = await page.evaluate(async () => {
    const original = window.MediaRecorder
    class MockMediaRecorder {
      static isTypeSupported(type: string) {
        return type === 'audio/mp4'
      }
    }
    Object.defineProperty(window, 'MediaRecorder', { value: MockMediaRecorder, configurable: true })
    const mod = await import('/src/student/interview/voice.ts')
    const result = mod.pickSupportedAudioMimeType()
    Object.defineProperty(window, 'MediaRecorder', { value: original, configurable: true })
    return result
  })

  expect(selected).toBe('audio/mp4')
})

test('answer submission shows staged progress bar while follow-up is running', async ({ page }) => {
  await mockStudentApi(page)
  await page.route('**/api/v1/student/interviews/runs/start', async (route) => {
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 1, msg: 'stream disabled', data: null }) })
  })
  await page.route('**/api/v1/student/interviews/1/turns/runs/submit', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1000))
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(ok({ run_id: 'answer-run-1' })) })
  })
  await page.route('**/api/v1/student/interviews/runs/answer-run-1/events?**', async (route) => {
    const body = [
      'event: runtime.status',
      'data: {"seq":1,"phase":"retrieval","label":"正在检索题库和岗位知识"}',
      '',
      'event: done',
      'data: {"seq":2}',
      '',
      '',
    ].join('\n')
    await route.fulfill({ contentType: 'text/event-stream', body })
  })

  await page.goto('/student/interviewer')
  await page.getByPlaceholder(/Java/).fill('后端工程师')
  await page.getByPlaceholder(/JD/).fill('负责 Java、Redis、MySQL、系统设计和线上稳定性。')
  await page.locator('.interview-config-panel button.arco-btn-primary').last().click()
  await expect(page.locator('.interview-answer-box')).toBeVisible()

  await page.locator('.interview-answer-box textarea').fill('我负责后端接口和 Redis 缓存优化。')
  await page.locator('.interview-answer-box button.arco-btn-primary').click()

  await expect(page.locator('.interview-answer-progress')).toBeVisible()
  await expect(page.locator('.interview-answer-progress-step--active')).toContainText(/读取回答|检索题库/)
})

test('answer submission immediately reassures the user before the follow-up is ready', async ({ page }) => {
  await mockStudentApi(page)
  await page.route('**/api/v1/student/interviews/runs/start', async (route) => {
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 1, msg: 'stream disabled', data: null }) })
  })
  await page.route('**/api/v1/student/interviews/1/turns/runs/submit', async (route) => {
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(ok({ run_id: 'answer-run-instant' })) })
  })
  await page.route('**/api/v1/student/interviews/runs/answer-run-instant/events?**', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500))
    const body = [
      'event: done',
      'data: {"seq":1}',
      '',
      '',
    ].join('\n')
    await route.fulfill({ contentType: 'text/event-stream', body })
  })

  await page.goto('/student/interviewer')
  await page.getByPlaceholder(/Java/).fill('后端工程师')
  await page.getByPlaceholder(/JD/).fill('负责 Java、Redis、MySQL、系统设计和线上稳定性。')
  await page.locator('.interview-config-panel button.arco-btn-primary').last().click()
  await expect(page.locator('.interview-answer-box')).toBeVisible()

  await page.locator('.interview-answer-box textarea').fill('我负责接口性能优化，用 Redis 缓存降低了查询压力。')
  await page.locator('.interview-answer-box button.arco-btn-primary').click()

  await expect(page.locator('.interview-instant-coach')).toContainText('收到，我先抓住你这段回答里的重点')
})

test('resume source picker loads online resumes and closes after selection', async ({ page }) => {
  await mockStudentApi(page)
  await page.goto('/student/interviewer')

  await page.locator('.interview-resume-select').click()
  const resumeMenu = page.locator('.interview-resume-menu')
  await expect(resumeMenu).toBeVisible()
  await expect(resumeMenu.getByText('梁伟业简历_java开发.pdf')).toBeVisible()
  await expect(resumeMenu.getByText('Agent开发实习生简历')).toBeVisible()

  await resumeMenu.getByText('Agent开发实习生简历').click()
  await expect(page.locator('.interview-resume-menu')).toHaveCount(0)
  await expect(page.locator('.interview-resume-select')).toContainText('Agent开发实习生简历')
})
test('guided interview entry starts with role and resume before advanced settings', async ({ page }) => {
  await mockStudentApi(page)
  let capturedStartBody: Record<string, unknown> | null = null
  await page.route('**/api/v1/student/interviews/runs/start', async (route) => {
    capturedStartBody = route.request().postDataJSON() as Record<string, unknown>
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(ok({ run_id: 'run-quick-start', request_id: 'req-quick-start' })),
    })
  })
  await page.route('**/api/v1/student/interviews/runs/run-quick-start/events?**', async (route) => {
    const body = [
      'event: interview.started',
      'data: {"seq":1,"session":{"id":2,"target_role":"后端工程师","interview_type":"first_round","interview_style":"strict","difficulty":"normal","round_limit":8,"status":"active"},"first_turn":{"id":21,"turn_index":1,"question":"先介绍一个你最熟悉的后端项目。","answer":null},"knowledge_status":{"document_count":1,"chunk_count":4,"retriever":"mock","vector_ready":true}}',
      '',
      'event: done',
      'data: {"seq":2}',
      '',
      '',
    ].join('\n')
    await route.fulfill({ contentType: 'text/event-stream', body })
  })

  await page.goto('/student/interviewer')

  await expect(page.locator('.interview-quick-start')).toBeVisible()
  await expect(page.locator('.interview-quick-start-summary')).toHaveCount(0)
  await expect(page.locator('.interview-field').filter({ hasText: '目标岗位' })).toBeVisible()
  await expect(page.getByText('岗位 JD / 岗位要求')).toBeVisible()
  await expect(page.getByText('默认会带上最近简历直接开练')).toHaveCount(0)

  await page.getByPlaceholder(/Java/).fill('后端工程师')
  await page.getByRole('button', { name: '立即开始模拟' }).click()

  await expect(page.locator('.interview-answer-box')).toBeVisible()
  expect(capturedStartBody?.target_role).toBe('后端工程师')
  expect(String(capturedStartBody?.job_description ?? '')).not.toBe('')
})

test('advanced settings stay folded until the user asks for more control', async ({ page }) => {
  await mockStudentApi(page)
  await page.goto('/student/interviewer')

  await expect(page.locator('.interview-advanced-settings')).not.toHaveAttribute('open', '')
  await expect(page.locator('.interview-deferred-stack').first()).not.toBeVisible()
  await expect(page.locator('.interview-deferred-stack').last()).not.toBeVisible()

  await page.locator('.interview-advanced-settings summary').click()
  await expect(page.locator('.interview-advanced-settings')).toHaveAttribute('open', '')
  await expect(page.locator('.interview-deferred-stack').first()).toBeVisible()
  await expect(page.locator('.interview-deferred-stack').last()).toBeVisible()
})

test('newbie starter choices fill role and JD so first practice feels guided', async ({ page }) => {
  await mockStudentApi(page)
  let capturedStartBody: Record<string, unknown> | null = null
  await page.route('**/api/v1/student/interviews/runs/start', async (route) => {
    capturedStartBody = route.request().postDataJSON() as Record<string, unknown>
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(ok({ run_id: 'run-starter-choice', request_id: 'req-starter-choice' })),
    })
  })
  await page.route('**/api/v1/student/interviews/runs/run-starter-choice/events?**', async (route) => {
    const body = [
      'event: interview.started',
      'data: {"seq":1,"session":{"id":4,"target_role":"后端开发工程师","interview_type":"first_round","interview_style":"strict","difficulty":"normal","round_limit":8,"status":"active"},"first_turn":{"id":41,"turn_index":1,"question":"先讲一个你做过的后端项目。","answer":null},"knowledge_status":{"document_count":1,"chunk_count":4,"retriever":"mock","vector_ready":true}}',
      '',
      'event: done',
      'data: {"seq":2}',
      '',
      '',
    ].join('\n')
    await route.fulfill({ contentType: 'text/event-stream', body })
  })

  await page.goto('/student/interviewer')
  await expect(page.getByText('不知道怎么填，先选一个方向')).toBeVisible()

  await page.getByRole('button', { name: /后端开发/ }).click()
  await expect(page.getByPlaceholder(/Java/)).toHaveValue('后端开发工程师')
  await expect(page.getByPlaceholder(/JD/)).toHaveValue(/Java|Redis|MySQL/)

  await page.getByRole('button', { name: '立即开始模拟' }).click()
  await expect(page.locator('.interview-answer-box')).toBeVisible()
  expect(capturedStartBody?.target_role).toBe('后端开发工程师')
  expect(String(capturedStartBody?.job_description ?? '')).toContain('Redis')
})

test('newbie coach helpers show answer templates and can fill the answer box', async ({ page }) => {
  await mockStudentApi(page)
  await page.route('**/api/v1/student/interviews/runs/start', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(ok({ run_id: 'run-helper-start', request_id: 'req-helper-start' })),
    })
  })
  await page.route('**/api/v1/student/interviews/runs/run-helper-start/events?**', async (route) => {
    const body = [
      'event: interview.started',
      'data: {"seq":1,"session":{"id":3,"target_role":"后端工程师","interview_type":"first_round","interview_style":"strict","difficulty":"normal","round_limit":8,"status":"active"},"first_turn":{"id":31,"turn_index":1,"question":"请做一个 30 秒的自我介绍。","answer":null},"knowledge_status":{"document_count":1,"chunk_count":4,"retriever":"mock","vector_ready":true}}',
      '',
      'event: done',
      'data: {"seq":2}',
      '',
      '',
    ].join('\n')
    await route.fulfill({ contentType: 'text/event-stream', body })
  })

  await page.goto('/student/interviewer')
  await expect(page.getByText('新手开练建议')).toBeVisible()

  await page.getByPlaceholder(/Java/).fill('后端工程师')
  await page.getByRole('button', { name: '立即开始模拟' }).click()

  await expect(page.locator('.interview-answer-box')).toBeVisible()
  await expect(page.getByText('不用想完再开口')).toBeVisible()
  await page.getByRole('button', { name: '项目经历模板' }).click()
  await expect(page.locator('.interview-answer-box textarea')).toHaveValue(/背景|任务|结果/)
})

test('uploaded resume shows a compact summary card before parsing details', async ({ page }) => {
  await mockStudentApi(page)
  await page.route('**/api/v1/student/interviews/resume/extract', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(ok({
        filename: '吴少然-Agent开发工程师实习生简历.pdf',
        extracted_text: 'A'.repeat(873),
        chars: 873,
        confidence: 0.8,
        fallback_reason: 'recovered',
        anchors: [
          { name: '智能简历优化助手 Agent 应用开发', score: 0.8 },
          { name: '服务治理项目', score: 0.72 },
        ],
        best_opening_anchor: { name: '智能简历优化助手 Agent 应用开发', score: 0.8 },
        resume_blocks: {
          projects: [{}, {}, {}],
          work_experience: [],
          internship_experience: [],
          education: [{}],
        },
        attempts: [
          {
            strategy: '_strategy_structured_resume',
            valid_anchor_count: 5,
            failure_reason: 'recovered',
            confidence: 0.8,
            block_counts: {
              projects: 3,
              work_experience: 0,
              internship_experience: 0,
              education: 1,
            },
          },
        ],
        ocr_attempts: [],
      })),
    })
  })

  await page.goto('/student/interviewer')
  await page.locator('input[type="file"]').setInputFiles({
    name: 'resume.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('mock resume'),
  })

  await expect(page.locator('.interview-resume-brief-card')).toBeVisible()
  await expect(page.locator('.interview-resume-brief-title')).toHaveCount(0)
  await expect(page.locator('.interview-resume-brief-anchor')).toContainText('智能简历优化助手 Agent 应用开发')
  await expect(page.locator('.interview-resume-brief-metrics')).toBeVisible()
  await expect(page.locator('.interview-resume-brief-metrics')).toContainText('已经比较贴岗')
  const metricTexts = await page.locator('.interview-resume-brief-metric-main strong').evaluateAll((nodes) =>
    nodes.map((node) => {
      const rect = node.getBoundingClientRect()
      return { width: rect.width, height: rect.height }
    }),
  )
  expect(metricTexts.every((rect) => rect.width > rect.height * 1.6)).toBe(true)
  await expect(page.locator('.interview-resume-brief-details')).not.toHaveAttribute('open', '')

  await page.locator('.interview-resume-brief-details summary').click()
  await expect(page.locator('.interview-resume-brief-details')).toHaveAttribute('open', '')
  await expect(page.locator('.interview-resume-brief-timeline')).toBeVisible()
})

test('resume upload shows a friendly progress card while parsing is slow', async ({ page }) => {
  await mockStudentApi(page)
  await page.route('**/api/v1/student/interviews/resume/extract', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500))
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(ok({
        filename: 'slow-resume.pdf',
        extracted_text: 'A'.repeat(240),
        chars: 240,
        estimated_tokens: 160,
        confidence: 0.72,
        anchors: [],
        resume_blocks: {},
        attempts: [],
        ocr_attempts: [],
      })),
    })
  })

  await page.goto('/student/interviewer')
  await page.locator('input[type="file"]').setInputFiles({
    name: 'slow-resume.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('mock resume'),
  })

  await expect(page.locator('.interview-resume-upload-live-card')).toBeVisible()
  await expect(page.locator('.interview-resume-upload-live-card')).toContainText('先提取可用于开练的文字')
})

test('report view surfaces next-step actions after generating the report', async ({ page }) => {
  await mockStudentApi(page)
  await page.route('**/api/v1/student/interviews/runs/start', async (route) => {
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ code: 1, msg: 'stream disabled', data: null }),
    })
  })
  await page.route('**/api/v1/student/interviews/1/report/run', async (route) => {
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(ok({ run_id: 'report-run-1' })) })
  })
  await page.route('**/api/v1/student/interviews/runs/report-run-1/events?**', async (route) => {
    const body = [
      'event: interview.report.created',
      'data: {"overall_score":72,"dimension_scores":{"technical_accuracy":68,"project_evidence":74,"problem_solving":70,"communication":78,"job_fit":73,"pressure_handling":69},"strengths":["结构完整"],"weaknesses":["回答不够具体"],"suggestions":["补充量化结果"],"next_questions":["请继续追问项目指标"],"report_text":"你最大的问题是回答偏泛。","training_plan":[{"day":1,"focus":"项目细节","tasks":["复述一个项目的目标、动作、结果"],"expected_output":"能说出量化指标"}],"rewrite_examples":[{"original":"我做了缓存优化","rewritten":"我负责 Redis 热点 Key 优化，将接口 P95 从 420ms 降到 180ms","explanation":"补足动作和结果"}],"next_session_preset":{"target_role":"后端工程师","interview_type":"first_round","interview_style":"strict"}}',
      '',
      'event: done',
      'data: {"seq":2}',
      '',
      '',
    ].join('\n')
    await route.fulfill({ contentType: 'text/event-stream', body })
  })

  await page.goto('/student/interviewer')
  await page.getByPlaceholder(/Java/).fill('后端工程师')
  await page.locator('.interview-config-panel button.arco-btn-primary').last().click()
  await expect(page.locator('.interview-answer-box')).toBeVisible()

  await page.getByRole('button', { name: '结束本轮，拿改进建议' }).click()

  await expect(page.getByRole('button', { name: '按此计划再练一场' })).toBeVisible()
  await expect(page.getByRole('button', { name: '去优化简历表达' })).toBeVisible()
  await expect(page.getByRole('button', { name: '生成明天训练计划' })).toBeVisible()
})

test('report view presents fallback scoring as a friendly quick report instead of an error', async ({ page }) => {
  await mockStudentApi(page)
  await page.route('**/api/v1/student/interviews/runs/start', async (route) => {
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ code: 1, msg: 'stream disabled', data: null }),
    })
  })
  await page.route('**/api/v1/student/interviews/1/report/run', async (route) => {
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(ok({ run_id: 'report-run-friendly' })) })
  })
  await page.route('**/api/v1/student/interviews/runs/report-run-friendly/events?**', async (route) => {
    const body = [
      'event: interview.report.created',
      'data: {"overall_score":70,"dimension_scores":{"technical_accuracy":66,"project_evidence":61,"problem_solving":70,"communication":78,"job_fit":72,"pressure_handling":68},"strengths":["表达完整"],"weaknesses":["项目证据不足"],"suggestions":["补充量化结果"],"next_questions":["继续追问项目指标"],"report_text":"已先生成一版快速复盘。","comparison":{"has_previous":false,"message":"首次面试记录","scoring":{"mode":"local_fallback","model":"deepseek-v4-pro","usage":{"total_tokens":9999}}},"training_plan":[{"day":1,"focus":"项目证据","tasks":["补项目指标"],"expected_output":"一段 2 分钟回答"}],"rewrite_examples":[],"next_session_preset":{"target_role":"后端工程师","interview_type":"first_round","interview_style":"strict"}}',
      '',
      'event: done',
      'data: {"seq":2}',
      '',
      '',
    ].join('\n')
    await route.fulfill({ contentType: 'text/event-stream', body })
  })

  await page.goto('/student/interviewer')
  await page.getByPlaceholder(/Java/).fill('后端工程师')
  await page.locator('.interview-config-panel button.arco-btn-primary').last().click()
  await expect(page.locator('.interview-answer-box')).toBeVisible()

  await page.getByRole('button', { name: '结束本轮，拿改进建议' }).click()

  await expect(page.locator('.report-scoring-meta')).toContainText('已先生成快速报告')
  await expect(page.locator('.report-scoring-meta')).not.toContainText('本地兜底')
  await expect(page.locator('.report-scoring-meta')).not.toContainText('deepseek-v4-pro')
  await expect(page.locator('.report-scoring-meta')).not.toContainText('tokens')
})
