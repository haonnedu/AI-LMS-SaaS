/**
 * PILOT-01 — end-to-end pilot journey through the Next.js BFF (skeleton).
 *
 * teacher login → upload source → embed → AI draft questions (fake provider) → teacher review
 * (confirm keys) → blueprint → exam from blueprint → publish → class + invitation → assignment →
 * student login + join → start → autosave (quiz page) → submit (+ replay) → worker grades →
 * close → release scores → student results page → release solutions.
 *
 * SKIPPED unless EDUVIA_E2E=1 and the stack below is reachable. It has not been run yet.
 *
 * Stack (same loopback fixture as tests/auth, see discuss/2026-10-23-auth-implementation.md):
 *   1. From the repo root: `docker compose -f compose.auth-test.yaml up -d --wait` (PostgreSQL on
 *      127.0.0.1:5434, Redis on 127.0.0.1:6381) and an S3-compatible store for uploads, e.g. the
 *      `minio` service of compose.yaml on 127.0.0.1:9000 with the dev bucket from backend/.env.example.
 *   2. Migrate a disposable `*_test` database as the administrator (backend/README.md
 *      "Auth integration tests"): `AUTH_TEST_DATABASE_URL=... python -m pytest tests/test_bootstrap.py`
 *      once, or `alembic upgrade head` with DATABASE_URL pointing at it.
 *   3. Start a Celery worker AND beat against the same DB/Redis with APP_ENV=test (fake LLM, local
 *      embedder), e.g. from backend/:
 *        APP_ENV=test DATABASE_URL=postgresql+psycopg://eduvia_runtime:runtime_test_only@127.0.0.1:5434/eduvia_auth_test \
 *        CELERY_BROKER_URL=redis://127.0.0.1:6381/1 REDIS_URL=redis://127.0.0.1:6381/0 \
 *        celery -A app.worker:celery_app worker --beat -Q default,ingestion,generation,export,omr
 *      (Celery prefork does not run on Windows; use WSL/Linux or `--pool=solo`.)
 *   4. `EDUVIA_E2E=1 npx playwright test --project=e2e` from frontend/. Playwright's webServer
 *      entries start the OIDC fixture (:9101), the API (:8005, APP_ENV=test) and Next.js (:3105).
 *      The API must see the same S3_* settings as the worker (export them before running).
 *
 * Overrides: E2E_BASE_URL (default http://127.0.0.1:3105), E2E_API_URL (default
 * http://127.0.0.1:8005), E2E_PASSWORD (fixture password), E2E_TIMEOUT_MS (job polling, 120000).
 * All API steps use the browser context's `request` (session cookie) plus Origin + X-CSRF-Token,
 * exactly like the UI; the backend is never called directly with a token.
 */
/* eslint-disable @typescript-eslint/no-explicit-any -- E2E reads untyped JSON from the BFF; contract types live in src/lib/api/generated.ts. */
import { test, expect, type APIRequestContext, type APIResponse, type BrowserContext, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

const BASE = process.env.E2E_BASE_URL || "http://127.0.0.1:3105";
const API = process.env.E2E_API_URL || "http://127.0.0.1:8005";
const PASSWORD = process.env.E2E_PASSWORD || "Test-password-123!";
const JOB_TIMEOUT = Number(process.env.E2E_TIMEOUT_MS || 120000);
const ENABLED = process.env.EDUVIA_E2E === "1";
const KEY_FIELDS = /"(correctKey|answerKey|explanation|rationale)"\s*:/;

let reachable: Promise<string | null> | undefined;
/** Resolves to null when the frontend and API answer, else a reason for skipping. */
function stackReachable(): Promise<string | null> {
  reachable ??= (async () => {
    for (const url of [`${BASE}/login`, `${API}/health/live`]) {
      try {
        const response = await fetch(url, { signal: AbortSignal.timeout(5000) });
        if (!response.ok) return `${url} answered ${response.status}`;
      } catch {
        return `${url} is not reachable`;
      }
    }
    return null;
  })();
  return reachable;
}

type Session = { context: BrowserContext; page: Page; api: Api };

class Api {
  constructor(private readonly request: APIRequestContext, private readonly csrf: string) {}
  private headers(extra: Record<string, string> = {}) {
    return { Origin: new URL(BASE).origin, "X-CSRF-Token": this.csrf, ...extra };
  }
  /** Calls `/api/backend/<path>` and fails with the route and status (a 404 usually means the BFF route is missing). */
  async call<T = any>(method: "GET" | "POST" | "PUT" | "DELETE", path: string, options: { data?: unknown; headers?: Record<string, string>; body?: string; expect?: number[] } = {}): Promise<T> {
    const url = `/api/backend/${path.replace(/^\//, "")}`;
    const init = { headers: method === "GET" ? {} : this.headers(options.headers), data: options.body ?? options.data };
    const response: APIResponse = await this.request.fetch(url, { method, ...init });
    const allowed = options.expect ?? [200, 201, 202];
    if (!allowed.includes(response.status())) {
      throw new Error(`${method} ${url} -> ${response.status()} ${(await response.text()).slice(0, 300)}`);
    }
    const type = response.headers()["content-type"] || "";
    return (type.includes("application/json") ? await response.json() : await response.text()) as T;
  }
  get<T = any>(path: string) { return this.call<T>("GET", path); }
  post<T = any>(path: string, data?: unknown, headers?: Record<string, string>) { return this.call<T>("POST", path, { data, headers }); }
  put<T = any>(path: string, data?: unknown) { return this.call<T>("PUT", path, { data }); }
}

/** Login through the OIDC fixture exactly like tests/auth/login.spec.ts, then open the personal workspace. */
async function signIn(context: BrowserContext, role: string): Promise<Session> {
  const page = await context.newPage();
  await page.goto("/login");
  await page.getByRole("link", { name: "Đăng nhập", exact: true }).click();
  await page.getByLabel("Email", { exact: true }).fill(`${role}-${Date.now()}-${randomUUID().slice(0, 6)}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/onboarding/);
  await page.getByRole("button", { name: "Mở workspace cá nhân" }).click();
  await expect(page).toHaveURL(/dashboard/);
  const session = await (await context.request.get("/api/session")).json();
  expect(session.authenticated).toBe(true);
  expect(JSON.stringify(session)).not.toContain("accessToken");
  return { context, page, api: new Api(context.request, session.csrfToken) };
}

/** Polls `read` until `done` holds; fails with the last value after JOB_TIMEOUT. */
async function until<T>(label: string, read: () => Promise<T>, done: (value: T) => boolean, failed?: (value: T) => boolean): Promise<T> {
  const started = Date.now();
  let last: T | undefined;
  while (Date.now() - started < JOB_TIMEOUT) {
    last = await read();
    if (failed?.(last)) throw new Error(`${label} failed: ${JSON.stringify(last).slice(0, 400)}`);
    if (done(last)) return last;
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
  throw new Error(`${label} timed out after ${JOB_TIMEOUT} ms (is the Celery worker running?): ${JSON.stringify(last).slice(0, 400)}`);
}

const jobDone = (api: Api, ws: string, jobId: string, label: string) =>
  until(label, () => api.get(`workspaces/${ws}/jobs/${jobId}`), (job: any) => job.status === "succeeded", (job: any) => ["failed", "cancelled"].includes(job.status));

test.describe.configure({ mode: "serial" });

test.describe("pilot journey: teacher → student → score", () => {
  test.beforeEach(async () => {
    test.skip(!ENABLED, "Set EDUVIA_E2E=1 and start the stack described at the top of this file.");
    const reason = await stackReachable();
    test.skip(reason !== null, `E2E stack unavailable: ${reason}`);
  });

  test("full journey with key-leak checks at every student step", async ({ browser }) => {
    test.setTimeout(JOB_TIMEOUT * 6);
    const teacher = await signIn(await browser.newContext({ baseURL: BASE }), "teacher");
    const t = teacher.api;
    const workspaces = await t.get("workspaces");
    const ws: string = workspaces.items.find((w: any) => w.role === "owner")?.id ?? workspaces.items[0].id;

    // ---- curriculum metadata (seeded by migration 0011)
    const subjects = await t.get("curriculum/subjects");
    const toan = subjects.items.find((s: any) => s.code === "toan");
    expect(toan, "seeded subject 'toan'").toBeTruthy();
    const units = await t.get("curriculum/units?subject=toan&grade=10");
    const unitId: string = units.items[0].id;

    // ---- upload a rights-attested source and wait for ingestion, then embedding
    const upload = await t.call("POST", `workspaces/${ws}/documents`, {
      body: "Mệnh đề là một câu khẳng định có tính đúng hoặc sai. Tập hợp là một khái niệm cơ bản của toán học.\n".repeat(40),
      headers: { "Content-Type": "text/plain; charset=utf-8", "X-File-Name": encodeURIComponent("e2e-menh-de.txt"), "X-Rights-Attested": "true", "Idempotency-Key": randomUUID() },
      expect: [202],
    });
    const documentId: string = upload.document.id;
    await jobDone(t, ws, upload.job.id, "document.ingest");
    const embed = await t.post(`workspaces/${ws}/documents/${documentId}/embed`);
    await jobDone(t, ws, embed.job.id, "document.embed");

    // ---- AI draft questions with the fake provider (APP_ENV=test)
    const accepted = await t.post(`workspaces/${ws}/generation/drafts`, {
      purpose: "questions", curriculumUnitId: unitId, grade: 10, subject: "toan",
      objectives: ["Nhận biết mệnh đề"], documentIds: [documentId], count: 2, cognitiveLevel: "remember",
    }, { "Idempotency-Key": randomUUID() });
    const generation = await until("questions.generate",
      () => t.get(`workspaces/${ws}/generation/jobs/${accepted.generationJob.id}`),
      (g: any) => g.finishedAt !== null, (g: any) => g.validationStatus === "failed");
    expect(generation.validationStatus).toBe("valid");
    expect(generation.questionIds).toHaveLength(2);

    // ---- teacher review: read each draft (teacher DTO has the key) and confirm the key -> active
    for (const questionId of generation.questionIds as string[]) {
      const question = await t.get(`workspaces/${ws}/questions/${questionId}`);
      expect(question.stem.length).toBeGreaterThan(0);
      const reviewed = await t.put(`workspaces/${ws}/questions/${questionId}/key`, { correctKey: question.correctKey ?? question.choices[0].key });
      expect(reviewed.status).toBe("active");
    }

    // ---- blueprint (2 × remember on the unit, 10 points) → validate → publish
    const blueprint = await t.post(`workspaces/${ws}/blueprints`, {
      title: "E2E kiểm tra 15 phút", subjectId: toan.id, grade: 10, examKind: "periodic", durationMinutes: 15,
      totalPoints: 10, effectiveYear: new Date().getUTCFullYear(), provenance: "E2E pilot journey",
      body: {
        parts: [{ code: "P1", title: "Trắc nghiệm", slots: [1, 2].map(index => ({ index, itemType: "single_choice", points: "5.00", curriculumUnitId: unitId, cognitiveLevel: "remember" })) }],
        matrix: [{ curriculumUnitId: unitId, cognitiveLevel: "remember", count: 2 }],
      },
    });
    const versionNo = blueprint.latestVersion?.versionNo ?? 1;
    await t.post(`workspaces/${ws}/blueprints/${blueprint.id}/versions/${versionNo}/validate`);
    const blueprintVersion = await t.post(`workspaces/${ws}/blueprints/${blueprint.id}/versions/${versionNo}/publish`);
    expect(blueprintVersion.status).toBe("published");

    // ---- exam from blueprint → publish; the student view never carries keys
    const exam = await t.post(`workspaces/${ws}/exams`, { blueprintVersionId: blueprintVersion.id, seed: "e2e" });
    const published = await t.post(`workspaces/${ws}/exams/${exam.id}/versions/${exam.currentVersion.versionNo}/publish`);
    const examVersionId: string = published.currentVersion.id;
    expect(published.currentVersion.status).toBe("published");
    const studentView = await t.get(`workspaces/${ws}/exams/${exam.id}/versions/${published.currentVersion.versionNo}/student-view`);
    expect(JSON.stringify(studentView)).not.toMatch(KEY_FIELDS);

    // ---- class, invitation, assignment (manual score + solution release) → publish
    const klass = await t.post(`workspaces/${ws}/classes`, { name: "E2E 10A1", gradeLevel: "10", subject: "Toán" });
    const invitation = await t.post(`workspaces/${ws}/classes/${klass.id}/invitations`, { expiresInHours: 24, maxUses: 5 });
    const now = Date.now();
    const assignment = await t.post(`workspaces/${ws}/classes/${klass.id}/assignments`, {
      examVersionId, title: "E2E bài kiểm tra", opensAt: new Date(now - 60_000).toISOString(),
      closesAt: new Date(now + 2 * 3600_000).toISOString(), timeLimitSeconds: 900, maxAttempts: 1,
      timezone: "Asia/Ho_Chi_Minh", scoreRelease: "manual", solutionRelease: "manual",
    });
    expect((await t.post(`workspaces/${ws}/assignments/${assignment.id}/publish`)).status).toBe("published");

    // ---- student: login, join, see the assignment
    const student = await signIn(await browser.newContext({ baseURL: BASE }), "student");
    const s = student.api;
    const joined = await s.post(`invitations/${invitation.token}/accept`);
    expect(joined.classId).toBe(klass.id);
    const mine = await s.get("student/assignments");
    expect(mine.items.map((a: any) => a.id)).toContain(assignment.id);
    expect(JSON.stringify(mine)).not.toMatch(KEY_FIELDS);

    // ---- start (idempotent replay returns the same attempt)
    const startKey = randomUUID();
    const started = await s.post(`student/assignments/${assignment.id}/attempts`, undefined, { "Idempotency-Key": startKey });
    const replayStart = await s.post(`student/assignments/${assignment.id}/attempts`, undefined, { "Idempotency-Key": startKey });
    expect(replayStart.attemptId).toBe(started.attemptId);
    const attemptId: string = started.attemptId;

    // ---- quiz page: items render without keys; choosing an option autosaves through the BFF
    const attempt = await s.get(`student/attempts/${attemptId}`);
    expect(JSON.stringify(attempt)).not.toMatch(KEY_FIELDS);
    expect(attempt.items).toHaveLength(2);
    await student.page.goto(`/student/attempts/${attemptId}`);
    await expect(student.page.getByText(attempt.items[0].stem, { exact: false })).toBeVisible();
    const autosave = student.page.waitForResponse(r => /\/api\/backend\/student\/attempts\/[^/]+\/answers\//.test(r.url()) && r.request().method() === "PUT");
    await student.page.getByRole("radio").first().check();
    expect((await autosave).status()).toBe(200);
    await student.page.screenshot({ path: "evidence/e2e/quiz-desktop.png", fullPage: true });

    // second item answered through the API (stale sequence is rejected)
    const second = attempt.items[1];
    await s.put(`student/attempts/${attemptId}/answers/${second.itemId}`, { selectedKey: second.choices[0].key, expectedRevision: second.answerRevision, clientSequence: 10 });
    await s.call("PUT", `student/attempts/${attemptId}/answers/${second.itemId}`, { data: { selectedKey: second.choices[1].key, expectedRevision: 0, clientSequence: 1 }, expect: [409] });

    // ---- submit (+ replay with the same key is a no-op returning the same snapshot)
    const submitKey = randomUUID();
    const submitted = await s.post(`student/attempts/${attemptId}/submit`, undefined, { "Idempotency-Key": submitKey });
    const replaySubmit = await s.post(`student/attempts/${attemptId}/submit`, undefined, { "Idempotency-Key": submitKey });
    expect(replaySubmit.snapshotSha256).toBe(submitted.snapshotSha256);
    expect(replaySubmit.replayed).toBe(true);

    // ---- before release: no score, no solution
    const pending = await s.get(`student/attempts/${attemptId}/results`);
    expect(pending.scoreReleased).toBe(false);
    expect(pending.score).toBeNull();
    expect(pending.items.every((i: any) => i.solution === null)).toBe(true);

    // ---- worker grades (attempt.grade job); teacher sees a graded row
    await until("attempt.grade",
      () => t.get(`workspaces/${ws}/assignments/${assignment.id}/results`),
      (r: any) => r.items.some((i: any) => i.attemptId === attemptId && i.gradingStatus === "graded"));

    // ---- close, release scores; student results page shows the score but still no solution
    await t.post(`workspaces/${ws}/assignments/${assignment.id}/close`);
    const release = await t.post(`workspaces/${ws}/assignments/${assignment.id}/release-scores`);
    expect(release.releasedGrades).toBeGreaterThanOrEqual(1);
    const scored = await s.get(`student/attempts/${attemptId}/results`);
    expect(scored.scoreReleased).toBe(true);
    expect(scored.score).not.toBeNull();
    expect(scored.items.every((i: any) => i.solution === null)).toBe(true);
    await student.page.goto(`/student/attempts/${attemptId}/results`);
    // The UI may format "10", "10.00" or the Vietnamese "10,00"; accept any of them.
    const score = Number(scored.score);
    const formats = [String(scored.score), String(score), score.toFixed(2).replace(".", ",")].map(v => v.replace(/[.]/g, "\\."));
    await expect(student.page.getByText(new RegExp(`(^|\\D)(${formats.join("|")})(\\D|$)`)).first()).toBeVisible();
    expect(await student.page.content()).not.toMatch(/correctKey|explanation/);
    await student.page.screenshot({ path: "evidence/e2e/results-desktop.png", fullPage: true });

    // ---- release solutions; only now the documented `solution` object appears
    await t.post(`workspaces/${ws}/assignments/${assignment.id}/release-solutions`);
    const solved = await s.get(`student/attempts/${attemptId}/results`);
    expect(solved.solutionsReleased).toBe(true);
    expect(solved.items.every((i: any) => i.solution && typeof i.solution.correctKey === "string")).toBe(true);

    // ---- isolation spot checks: the student cannot reach the teacher workspace routes
    await s.call("GET", `workspaces/${ws}/assignments/${assignment.id}/results`, { expect: [404] });
    await s.call("GET", `workspaces/${ws}/exams/${exam.id}`, { expect: [404] });

    await student.context.close();
    await teacher.context.close();
  });
});
