"""M5/M6 assessment: assignments, attempts, answers, grading results and grade revisions
(ASSIGN-01/02, ASMT-01..08).

* Every table is tenant-owned: ``workspace_id NOT NULL``, ``UNIQUE (workspace_id, id)``,
  composite (workspace_id, ...) foreign keys and the 0006/0009 FORCE RLS predicate. Teacher
  operations use these tables directly inside ``workspace_transaction``.
* ``assignments`` pins a class and an exam version. Once published the pin, the window start,
  time limit, attempt limit and release policies are frozen; ``closes_at`` may only move later;
  ``archived`` is terminal and release timestamps can never be cleared or rewritten.
* Students are NOT workspace members (0005), so RLS hides every tenant row from them. All
  student operations go through narrow SECURITY DEFINER functions owned by the NOLOGIN
  ``eduvia_identity_owner``. Each one derives the student from ``edu.actor_id()`` (verified
  identity set by ``set_identity``) joined to ``students.user_id`` in an active workspace, and
  never accepts a student or workspace id from the caller. Item DTOs are rebuilt from
  ``{key,text}`` only; answer keys are read solely by ``edu.student_results`` after the
  assignment's ``solutions_released_at`` is set.
* Attempt start serializes on ``pg_advisory_xact_lock(hashtext(assignment:student))`` and a
  partial unique index allows one ``in_progress`` attempt per (assignment, student). Answer
  writes and submit lock the attempt row, so a save and a submit can never interleave. Fresh
  ``clock_timestamp()`` is read after the lock. Writes are rejected after ``deadline_at`` plus
  a 5 second transport grace (EV010).
* Submit / deadline expiry share ``edu.finalize_attempt``: it freezes the answer snapshot
  (sha256), and enqueues one ``attempt.grade`` job in the same transaction (system idempotency
  key per attempt, requested by the assignment author so the worker runs with a verified
  teacher context). Whichever finalization commits first wins; later ones are no-ops that
  return the same snapshot.
* Grading results are append-only (no UPDATE grant). Grade revisions are append-only except
  the ``is_current`` true -> false flip and the one-way ``released_at`` stamp.
* Error codes: P0002 not found / not visible, 28000 no identity, 22023 invalid argument,
  EV010 deadline passed, EV011 idempotency conflict, EV012 assignment unavailable (window,
  class, enrollment), EV013 attempt limit reached, EV014 stale answer, EV015 attempt not in
  progress, EV016 option not part of the item.
"""

from alembic import op

revision = "0014_assessment"
down_revision = "0013_generation_exams"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "assignments",
    "quiz_attempts",
    "student_answers",
    "grading_results",
    "grading_result_items",
    "grades",
)

TENANT_PREDICATE = (
    "workspace_id::text = current_setting('edu.current_workspace_id', true) "
    "AND edu.can_read_workspace(workspace_id)"
)

GRACE = "interval '5 seconds'"

TABLES_SQL = """
CREATE TABLE edu.assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
  class_id uuid NOT NULL,
  exam_version_id uuid NOT NULL,
  title text NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 300),
  instructions text CHECK (instructions IS NULL OR length(instructions) <= 10000),
  opens_at timestamptz NOT NULL,
  closes_at timestamptz,
  time_limit_seconds integer
    CHECK (time_limit_seconds IS NULL OR time_limit_seconds BETWEEN 60 AND 86400),
  max_attempts integer NOT NULL DEFAULT 1 CHECK (max_attempts BETWEEN 1 AND 5),
  timezone text NOT NULL DEFAULT 'Asia/Ho_Chi_Minh' CHECK (length(timezone) BETWEEN 1 AND 64),
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','published','closed','archived')),
  score_release text NOT NULL DEFAULT 'manual'
    CHECK (score_release IN ('immediate','after_close','manual')),
  solution_release text NOT NULL DEFAULT 'manual'
    CHECK (solution_release IN ('never','after_close','manual')),
  scores_released_at timestamptz,
  solutions_released_at timestamptz,
  created_by_user_id uuid NOT NULL REFERENCES edu.users(id),
  published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_assignments_workspace_id UNIQUE (workspace_id, id),
  CONSTRAINT uq_assignments_version_pin UNIQUE (workspace_id, id, exam_version_id),
  CONSTRAINT fk_assignments_class FOREIGN KEY (workspace_id, class_id)
    REFERENCES edu.classes(workspace_id, id),
  CONSTRAINT fk_assignments_exam_version FOREIGN KEY (workspace_id, exam_version_id)
    REFERENCES edu.exam_versions(workspace_id, id),
  CONSTRAINT ck_assignments_window CHECK (closes_at IS NULL OR closes_at > opens_at),
  CONSTRAINT ck_assignments_after_close CHECK (
    closes_at IS NOT NULL OR (score_release <> 'after_close' AND solution_release <> 'after_close')
  ),
  CONSTRAINT ck_assignments_published CHECK (
    status NOT IN ('published','closed') OR published_at IS NOT NULL
  )
);
CREATE INDEX ix_assignments_class ON edu.assignments(workspace_id, class_id, created_at DESC);
CREATE INDEX ix_assignments_due_release ON edu.assignments(closes_at)
  WHERE status IN ('published','closed');

CREATE TABLE edu.quiz_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
  assignment_id uuid NOT NULL,
  student_id uuid NOT NULL,
  exam_version_id uuid NOT NULL,
  attempt_no integer NOT NULL CHECK (attempt_no BETWEEN 1 AND 100),
  status text NOT NULL DEFAULT 'in_progress'
    CHECK (status IN ('in_progress','submitted','graded','void')),
  started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  deadline_at timestamptz,
  submitted_at timestamptz,
  submission_recorded_at timestamptz,
  submission_reason text CHECK (submission_reason IN ('student','deadline','teacher')),
  idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
  request_hash text NOT NULL CHECK (length(request_hash) BETWEEN 1 AND 128),
  submit_idempotency_key text
    CHECK (submit_idempotency_key IS NULL OR length(submit_idempotency_key) BETWEEN 1 AND 200),
  submit_request_hash text
    CHECK (submit_request_hash IS NULL OR length(submit_request_hash) BETWEEN 1 AND 128),
  answer_sequence integer NOT NULL DEFAULT 0 CHECK (answer_sequence >= 0),
  submitted_snapshot_sha256 bytea
    CHECK (submitted_snapshot_sha256 IS NULL OR octet_length(submitted_snapshot_sha256) = 32),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_quiz_attempts_workspace_id UNIQUE (workspace_id, id),
  CONSTRAINT uq_quiz_attempts_version UNIQUE (workspace_id, id, exam_version_id),
  CONSTRAINT uq_quiz_attempts_number UNIQUE (assignment_id, student_id, attempt_no),
  CONSTRAINT uq_quiz_attempts_idempotency UNIQUE (assignment_id, student_id, idempotency_key),
  CONSTRAINT fk_quiz_attempts_assignment FOREIGN KEY (workspace_id, assignment_id, exam_version_id)
    REFERENCES edu.assignments(workspace_id, id, exam_version_id),
  CONSTRAINT fk_quiz_attempts_student FOREIGN KEY (workspace_id, student_id)
    REFERENCES edu.students(workspace_id, id),
  CONSTRAINT ck_quiz_attempts_deadline CHECK (deadline_at IS NULL OR deadline_at > started_at),
  CONSTRAINT ck_quiz_attempts_submitted CHECK (
    (status IN ('submitted','graded')) = (submitted_at IS NOT NULL AND submission_reason IS NOT NULL
      AND submitted_snapshot_sha256 IS NOT NULL AND submission_recorded_at IS NOT NULL)
    OR status = 'void'
  )
);
CREATE UNIQUE INDEX uq_quiz_attempts_in_progress ON edu.quiz_attempts(assignment_id, student_id)
  WHERE status = 'in_progress';
CREATE INDEX ix_quiz_attempts_assignment
  ON edu.quiz_attempts(workspace_id, assignment_id, student_id, attempt_no);
CREATE INDEX ix_quiz_attempts_student ON edu.quiz_attempts(student_id);
CREATE INDEX ix_quiz_attempts_due ON edu.quiz_attempts(deadline_at) WHERE status = 'in_progress';

CREATE TABLE edu.student_answers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
  attempt_id uuid NOT NULL,
  exam_version_id uuid NOT NULL,
  exam_item_id uuid NOT NULL,
  response jsonb NOT NULL CHECK (
    jsonb_typeof(response) = 'object' AND octet_length(response::text) <= 1000
  ),
  answer_revision integer NOT NULL DEFAULT 1 CHECK (answer_revision > 0),
  client_sequence bigint NOT NULL CHECK (client_sequence >= 0),
  saved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_student_answers_workspace_id UNIQUE (workspace_id, id),
  CONSTRAINT uq_student_answers_item UNIQUE (attempt_id, exam_item_id),
  CONSTRAINT fk_student_answers_attempt FOREIGN KEY (workspace_id, attempt_id, exam_version_id)
    REFERENCES edu.quiz_attempts(workspace_id, id, exam_version_id),
  CONSTRAINT fk_student_answers_item FOREIGN KEY (workspace_id, exam_version_id, exam_item_id)
    REFERENCES edu.exam_items(workspace_id, exam_version_id, id)
);

CREATE TABLE edu.grading_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
  attempt_id uuid NOT NULL,
  exam_version_id uuid NOT NULL,
  run_key text NOT NULL CHECK (length(run_key) BETWEEN 1 AND 200),
  input_hash text NOT NULL CHECK (length(input_hash) BETWEEN 1 AND 128),
  algorithm_version text NOT NULL CHECK (length(algorithm_version) BETWEEN 1 AND 32),
  source text NOT NULL CHECK (source IN ('online','manual')),
  raw_score numeric(10,2) NOT NULL CHECK (raw_score >= 0),
  max_score numeric(10,2) NOT NULL CHECK (max_score > 0),
  status text NOT NULL DEFAULT 'approved' CHECK (status IN ('proposed','approved','rejected')),
  supersedes_id uuid,
  created_by_user_id uuid REFERENCES edu.users(id),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_grading_results_workspace_id UNIQUE (workspace_id, id),
  CONSTRAINT uq_grading_results_run UNIQUE (attempt_id, run_key),
  CONSTRAINT uq_grading_results_attempt UNIQUE (workspace_id, attempt_id, id),
  CONSTRAINT uq_grading_results_version UNIQUE (workspace_id, id, exam_version_id),
  CONSTRAINT fk_grading_results_attempt FOREIGN KEY (workspace_id, attempt_id, exam_version_id)
    REFERENCES edu.quiz_attempts(workspace_id, id, exam_version_id),
  CONSTRAINT fk_grading_results_supersedes FOREIGN KEY (workspace_id, attempt_id, supersedes_id)
    REFERENCES edu.grading_results(workspace_id, attempt_id, id),
  CONSTRAINT ck_grading_results_bounds CHECK (raw_score <= max_score),
  CONSTRAINT ck_grading_results_manual CHECK (source <> 'manual' OR created_by_user_id IS NOT NULL)
);

CREATE TABLE edu.grading_result_items (
  grading_result_id uuid NOT NULL,
  workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
  exam_version_id uuid NOT NULL,
  exam_item_id uuid NOT NULL,
  effective_response jsonb NOT NULL CHECK (jsonb_typeof(effective_response) = 'object'),
  answer_source text NOT NULL CHECK (answer_source IN ('submitted','blank')),
  awarded_points numeric(10,2) NOT NULL CHECK (awarded_points >= 0),
  max_points numeric(10,2) NOT NULL CHECK (max_points > 0),
  reason text CHECK (reason IS NULL OR length(reason) <= 200),
  CONSTRAINT uq_grading_result_items_item UNIQUE (grading_result_id, exam_item_id),
  CONSTRAINT fk_grading_result_items_result
    FOREIGN KEY (workspace_id, grading_result_id, exam_version_id)
    REFERENCES edu.grading_results(workspace_id, id, exam_version_id),
  CONSTRAINT fk_grading_result_items_item
    FOREIGN KEY (workspace_id, exam_version_id, exam_item_id)
    REFERENCES edu.exam_items(workspace_id, exam_version_id, id),
  CONSTRAINT ck_grading_result_items_bounds CHECK (awarded_points <= max_points)
);

CREATE TABLE edu.grades (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
  attempt_id uuid NOT NULL,
  grading_result_id uuid NOT NULL,
  revision_no integer NOT NULL CHECK (revision_no > 0),
  score numeric(10,2) NOT NULL,
  max_score numeric(10,2) NOT NULL,
  is_current boolean NOT NULL DEFAULT true,
  approval_mode text NOT NULL CHECK (approval_mode IN ('automatic','teacher')),
  approved_by_user_id uuid REFERENCES edu.users(id),
  approved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  released_at timestamptz,
  reason text CHECK (reason IS NULL OR length(reason) BETWEEN 1 AND 2000),
  CONSTRAINT uq_grades_workspace_id UNIQUE (workspace_id, id),
  CONSTRAINT uq_grades_revision UNIQUE (attempt_id, revision_no),
  CONSTRAINT fk_grades_result FOREIGN KEY (workspace_id, attempt_id, grading_result_id)
    REFERENCES edu.grading_results(workspace_id, attempt_id, id),
  CONSTRAINT ck_grades_bounds CHECK (max_score > 0 AND score >= 0 AND score <= max_score),
  CONSTRAINT ck_grades_teacher CHECK (
    approval_mode <> 'teacher' OR (approved_by_user_id IS NOT NULL AND reason IS NOT NULL)
  )
);
CREATE UNIQUE INDEX uq_grades_current ON edu.grades(attempt_id) WHERE is_current;
CREATE INDEX ix_grades_workspace_attempt ON edu.grades(workspace_id, attempt_id);
"""

# Invoker guards: they run as the caller (runtime role under RLS, or the definer owner).
GUARDS_SQL = """
CREATE FUNCTION edu.assignment_guard() RETURNS trigger
  LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
  BEGIN
    IF TG_OP = 'INSERT' THEN
      IF NEW.status <> 'draft' OR NEW.published_at IS NOT NULL
         OR NEW.scores_released_at IS NOT NULL OR NEW.solutions_released_at IS NOT NULL THEN
        RAISE EXCEPTION 'assignments start as draft' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END IF;
    IF OLD.status = 'archived' THEN
      RAISE EXCEPTION 'archived assignment is immutable' USING ERRCODE = 'check_violation';
    END IF;
    IF (NEW.id, NEW.workspace_id, NEW.created_by_user_id, NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.workspace_id, OLD.created_by_user_id, OLD.created_at) THEN
      RAISE EXCEPTION 'assignment identity is immutable' USING ERRCODE = 'check_violation';
    END IF;
    IF NOT (NEW.status = OLD.status
            OR (OLD.status = 'draft' AND NEW.status IN ('published','archived'))
            OR (OLD.status = 'published' AND NEW.status IN ('closed','archived'))
            OR (OLD.status = 'closed' AND NEW.status = 'archived')) THEN
      RAISE EXCEPTION 'invalid assignment transition' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.published_at IS NOT NULL THEN
      -- The publication pin and attempt policy are frozen once students can see the work.
      IF (NEW.class_id, NEW.exam_version_id, NEW.opens_at, NEW.time_limit_seconds,
          NEW.max_attempts, NEW.timezone, NEW.score_release, NEW.solution_release,
          NEW.published_at)
         IS DISTINCT FROM
         (OLD.class_id, OLD.exam_version_id, OLD.opens_at, OLD.time_limit_seconds,
          OLD.max_attempts, OLD.timezone, OLD.score_release, OLD.solution_release,
          OLD.published_at) THEN
        RAISE EXCEPTION 'published assignment pin is immutable'
          USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.closes_at IS DISTINCT FROM OLD.closes_at
         AND (OLD.closes_at IS NULL OR NEW.closes_at IS NULL OR NEW.closes_at < OLD.closes_at)
      THEN
        RAISE EXCEPTION 'published closing time may only be extended'
          USING ERRCODE = 'check_violation';
      END IF;
    END IF;
    IF (OLD.scores_released_at IS NOT NULL
        AND NEW.scores_released_at IS DISTINCT FROM OLD.scores_released_at)
       OR (OLD.solutions_released_at IS NOT NULL
           AND NEW.solutions_released_at IS DISTINCT FROM OLD.solutions_released_at) THEN
      RAISE EXCEPTION 'release stamps are immutable' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END $$;
CREATE TRIGGER assignment_guard BEFORE INSERT OR UPDATE ON edu.assignments
  FOR EACH ROW EXECUTE FUNCTION edu.assignment_guard();

CREATE FUNCTION edu.quiz_attempt_guard() RETURNS trigger
  LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
  BEGIN
    IF (NEW.id, NEW.workspace_id, NEW.assignment_id, NEW.student_id, NEW.exam_version_id,
        NEW.attempt_no, NEW.started_at, NEW.idempotency_key, NEW.request_hash)
       IS DISTINCT FROM
       (OLD.id, OLD.workspace_id, OLD.assignment_id, OLD.student_id, OLD.exam_version_id,
        OLD.attempt_no, OLD.started_at, OLD.idempotency_key, OLD.request_hash) THEN
      RAISE EXCEPTION 'attempt identity is immutable' USING ERRCODE = 'check_violation';
    END IF;
    IF NOT (NEW.status = OLD.status
            OR (OLD.status = 'in_progress' AND NEW.status IN ('submitted','void'))
            OR (OLD.status = 'submitted' AND NEW.status IN ('graded','void'))
            OR (OLD.status = 'graded' AND NEW.status = 'void')) THEN
      RAISE EXCEPTION 'invalid attempt transition' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status <> 'in_progress' THEN
      IF (NEW.submitted_at, NEW.submission_recorded_at, NEW.submission_reason,
          NEW.submit_idempotency_key, NEW.submit_request_hash, NEW.submitted_snapshot_sha256,
          NEW.answer_sequence, NEW.deadline_at)
         IS DISTINCT FROM
         (OLD.submitted_at, OLD.submission_recorded_at, OLD.submission_reason,
          OLD.submit_idempotency_key, OLD.submit_request_hash, OLD.submitted_snapshot_sha256,
          OLD.answer_sequence, OLD.deadline_at) THEN
        RAISE EXCEPTION 'submitted attempt is frozen' USING ERRCODE = 'check_violation';
      END IF;
    ELSIF NEW.deadline_at IS DISTINCT FROM OLD.deadline_at
          AND (OLD.deadline_at IS NULL
               OR (NEW.deadline_at IS NOT NULL AND NEW.deadline_at < OLD.deadline_at)) THEN
      RAISE EXCEPTION 'attempt deadline may only be extended' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END $$;
CREATE TRIGGER quiz_attempt_guard BEFORE UPDATE ON edu.quiz_attempts
  FOR EACH ROW EXECUTE FUNCTION edu.quiz_attempt_guard();

CREATE FUNCTION edu.student_answer_guard() RETURNS trigger
  LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
  BEGIN
    IF TG_OP = 'UPDATE' AND (NEW.id, NEW.workspace_id, NEW.attempt_id, NEW.exam_version_id,
        NEW.exam_item_id) IS DISTINCT FROM (OLD.id, OLD.workspace_id, OLD.attempt_id,
        OLD.exam_version_id, OLD.exam_item_id) THEN
      RAISE EXCEPTION 'answer identity is immutable' USING ERRCODE = 'check_violation';
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.answer_revision <= OLD.answer_revision THEN
      RAISE EXCEPTION 'answer revision must increase' USING ERRCODE = 'check_violation';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM edu.quiz_attempts q
                   WHERE q.id = NEW.attempt_id AND q.workspace_id = NEW.workspace_id
                     AND q.status = 'in_progress') THEN
      RAISE EXCEPTION 'answers are frozen once the attempt leaves in_progress'
        USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END $$;
CREATE TRIGGER student_answer_guard BEFORE INSERT OR UPDATE ON edu.student_answers
  FOR EACH ROW EXECUTE FUNCTION edu.student_answer_guard();

CREATE FUNCTION edu.grade_guard() RETURNS trigger
  LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
  BEGIN
    IF TG_OP = 'INSERT' THEN
      IF NOT EXISTS (SELECT 1 FROM edu.grading_results r
                     WHERE r.id = NEW.grading_result_id AND r.attempt_id = NEW.attempt_id
                       AND r.status = 'approved' AND r.raw_score = NEW.score
                       AND r.max_score = NEW.max_score) THEN
        RAISE EXCEPTION 'grade must equal an approved grading result'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END IF;
    -- Append-only revisions: only the current flag may be cleared and release stamped once.
    IF (NEW.id, NEW.workspace_id, NEW.attempt_id, NEW.grading_result_id, NEW.revision_no,
        NEW.score, NEW.max_score, NEW.approval_mode, NEW.approved_by_user_id, NEW.approved_at,
        NEW.reason)
       IS DISTINCT FROM
       (OLD.id, OLD.workspace_id, OLD.attempt_id, OLD.grading_result_id, OLD.revision_no,
        OLD.score, OLD.max_score, OLD.approval_mode, OLD.approved_by_user_id, OLD.approved_at,
        OLD.reason) THEN
      RAISE EXCEPTION 'grade revisions are append-only' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.is_current AND NOT OLD.is_current THEN
      RAISE EXCEPTION 'a superseded grade cannot become current again'
        USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.released_at IS NOT NULL AND NEW.released_at IS DISTINCT FROM OLD.released_at THEN
      RAISE EXCEPTION 'grade release cannot be recalled' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END $$;
CREATE TRIGGER grade_guard BEFORE INSERT OR UPDATE ON edu.grades
  FOR EACH ROW EXECUTE FUNCTION edu.grade_guard();

REVOKE ALL ON FUNCTION edu.assignment_guard(), edu.quiz_attempt_guard(),
  edu.student_answer_guard(), edu.grade_guard() FROM PUBLIC;
"""

OWNER_ACCESS_SQL = """
GRANT CREATE ON SCHEMA edu TO eduvia_identity_owner;
GRANT SELECT, UPDATE ON edu.assignments TO eduvia_identity_owner;
GRANT SELECT, INSERT, UPDATE ON edu.quiz_attempts, edu.student_answers TO eduvia_identity_owner;
GRANT SELECT, UPDATE ON edu.grades TO eduvia_identity_owner;
GRANT SELECT ON edu.grading_results, edu.grading_result_items TO eduvia_identity_owner;
-- 0010 already lets the definer role read exam_answer_keys (exam_answer_keys_key_function);
-- these grants are idempotent repeats. Items/versions need definer policies for students.
GRANT SELECT ON edu.exam_versions, edu.exam_items, edu.exam_answer_keys TO eduvia_identity_owner;
GRANT INSERT ON edu.background_jobs TO eduvia_identity_owner;
CREATE POLICY assignments_assessment_function ON edu.assignments
  TO eduvia_identity_owner USING (true) WITH CHECK (true);
CREATE POLICY quiz_attempts_assessment_function ON edu.quiz_attempts
  TO eduvia_identity_owner USING (true) WITH CHECK (true);
CREATE POLICY student_answers_assessment_function ON edu.student_answers
  TO eduvia_identity_owner USING (true) WITH CHECK (true);
CREATE POLICY grades_assessment_function ON edu.grades
  TO eduvia_identity_owner USING (true) WITH CHECK (true);
CREATE POLICY grading_results_assessment_function ON edu.grading_results FOR SELECT
  TO eduvia_identity_owner USING (true);
CREATE POLICY grading_result_items_assessment_function ON edu.grading_result_items FOR SELECT
  TO eduvia_identity_owner USING (true);
CREATE POLICY exam_versions_assessment_function ON edu.exam_versions FOR SELECT
  TO eduvia_identity_owner USING (true);
CREATE POLICY exam_items_assessment_function ON edu.exam_items FOR SELECT
  TO eduvia_identity_owner USING (true);
CREATE POLICY background_jobs_assessment_enqueue ON edu.background_jobs FOR INSERT
  TO eduvia_identity_owner WITH CHECK (kind = 'attempt.grade');
"""

# Internal helpers: owned by the definer role, revoked from PUBLIC and never granted to the
# runtime role; they execute only inside the SECURITY DEFINER functions below.
HELPERS_SQL = """
-- The verified actor's active student row in an active workspace (NULL otherwise).
CREATE FUNCTION edu.assessment_actor_student(p_workspace_id uuid) RETURNS uuid
  LANGUAGE sql STABLE SET search_path=pg_catalog,edu AS $$
    SELECT s.id FROM edu.students s JOIN edu.workspaces w ON w.id = s.workspace_id
    WHERE s.workspace_id = p_workspace_id AND s.user_id = edu.actor_id()
      AND s.status = 'active' AND w.is_active
  $$;
ALTER FUNCTION edu.assessment_actor_student(uuid) OWNER TO eduvia_identity_owner;

-- Canonical answer snapshot, mirrored by app.services.scoring.snapshot_sha256:
-- sha256 of "<item uuid>:<selectedKey or empty>" lines joined by LF, ordered by item uuid.
CREATE FUNCTION edu.attempt_snapshot_sha256(p_attempt_id uuid) RETURNS bytea
  LANGUAGE sql STABLE SET search_path=pg_catalog,edu AS $$
    SELECT sha256(convert_to(coalesce(string_agg(
      a.exam_item_id::text || ':' || coalesce(a.response->>'selectedKey', ''), chr(10)
      ORDER BY a.exam_item_id), ''), 'UTF8'))
    FROM edu.student_answers a WHERE a.attempt_id = p_attempt_id
  $$;
ALTER FUNCTION edu.attempt_snapshot_sha256(uuid) OWNER TO eduvia_identity_owner;

-- Single finalization path for student submit, late submit and the deadline sweeper.
-- Caller holds the attempt row lock. Returns the grading job id (NULL when nothing changed).
CREATE FUNCTION edu.finalize_attempt(p_attempt_id uuid, p_reason text, p_now timestamptz,
    p_key text, p_hash text)
  RETURNS uuid LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
DECLARE
  att edu.quiz_attempts%ROWTYPE;
  author uuid;
  snapshot bytea;
  job uuid;
BEGIN
  SELECT q.* INTO att FROM edu.quiz_attempts q WHERE q.id = p_attempt_id FOR UPDATE;
  IF NOT FOUND OR att.status <> 'in_progress' THEN
    RETURN NULL;
  END IF;
  SELECT a.created_by_user_id INTO author FROM edu.assignments a
    WHERE a.workspace_id = att.workspace_id AND a.id = att.assignment_id;
  snapshot := edu.attempt_snapshot_sha256(att.id);
  UPDATE edu.quiz_attempts q SET status = 'submitted',
    submitted_at = CASE WHEN p_reason = 'deadline' AND att.deadline_at IS NOT NULL
                        THEN LEAST(att.deadline_at, p_now) ELSE p_now END,
    submission_recorded_at = p_now, submission_reason = p_reason,
    submit_idempotency_key = p_key, submit_request_hash = p_hash,
    submitted_snapshot_sha256 = snapshot, updated_at = p_now
    WHERE q.id = att.id;
  INSERT INTO edu.background_jobs(workspace_id, requested_by_user_id, kind, idempotency_key,
                                  request_hash, input)
    VALUES (att.workspace_id, author, 'attempt.grade',
            'system:attempt.grade:' || att.id::text, encode(snapshot, 'hex'),
            jsonb_build_object('attemptId', att.id::text))
    ON CONFLICT ON CONSTRAINT uq_background_jobs_idempotency DO NOTHING
    RETURNING id INTO job;
  RETURN job;
END $$;
ALTER FUNCTION edu.finalize_attempt(uuid, text, timestamptz, text, text)
  OWNER TO eduvia_identity_owner;
REVOKE ALL ON FUNCTION edu.assessment_actor_student(uuid), edu.attempt_snapshot_sha256(uuid),
  edu.finalize_attempt(uuid, text, timestamptz, text, text) FROM PUBLIC;
"""

STUDENT_READ_SQL = """
-- Published/closed assignments of the actor's active enrollments, across workspaces.
CREATE FUNCTION edu.student_assignments()
  RETURNS TABLE(out_assignment_id uuid, out_workspace_id uuid, out_class_id uuid,
                out_class_name text, out_class_active boolean, out_title text,
                out_opens_at timestamptz, out_closes_at timestamptz,
                out_time_limit_seconds integer, out_max_attempts integer, out_timezone text,
                out_status text, out_attempts_used integer, out_in_progress_attempt_id uuid,
                out_latest_attempt_id uuid, out_latest_attempt_status text,
                out_server_now timestamptz)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
    SELECT a.id, a.workspace_id, a.class_id, c.name::text, c.status = 'active', a.title,
      a.opens_at, a.closes_at, a.time_limit_seconds, a.max_attempts, a.timezone, a.status,
      (SELECT count(*)::integer FROM edu.quiz_attempts q
        WHERE q.assignment_id = a.id AND q.student_id = s.id AND q.status <> 'void'),
      (SELECT q.id FROM edu.quiz_attempts q
        WHERE q.assignment_id = a.id AND q.student_id = s.id AND q.status = 'in_progress'),
      l.id, l.status, clock_timestamp()
    FROM edu.students s
    JOIN edu.workspaces w ON w.id = s.workspace_id AND w.is_active
    JOIN edu.enrollments e ON e.workspace_id = s.workspace_id AND e.student_id = s.id
      AND e.status = 'active'
    JOIN edu.classes c ON c.workspace_id = e.workspace_id AND c.id = e.class_id
    JOIN edu.assignments a ON a.workspace_id = e.workspace_id AND a.class_id = e.class_id
      AND a.status IN ('published','closed')
    LEFT JOIN LATERAL (
      SELECT q.id, q.status FROM edu.quiz_attempts q
      WHERE q.assignment_id = a.id AND q.student_id = s.id AND q.status <> 'void'
      ORDER BY q.attempt_no DESC LIMIT 1
    ) l ON true
    WHERE s.user_id = edu.actor_id() AND s.status = 'active'
    ORDER BY a.opens_at DESC, a.id
    LIMIT 200
  $$;

CREATE FUNCTION edu.student_assignment_detail(p_assignment_id uuid)
  RETURNS TABLE(out_assignment_id uuid, out_workspace_id uuid, out_class_id uuid,
                out_class_name text, out_class_active boolean, out_title text,
                out_instructions text, out_opens_at timestamptz, out_closes_at timestamptz,
                out_time_limit_seconds integer, out_max_attempts integer, out_timezone text,
                out_status text, out_item_count integer, out_total_points numeric,
                out_attempts_used integer, out_in_progress_attempt_id uuid,
                out_latest_attempt_id uuid, out_latest_attempt_status text,
                out_server_now timestamptz)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
    SELECT a.id, a.workspace_id, a.class_id, c.name::text, c.status = 'active', a.title,
      a.instructions, a.opens_at, a.closes_at, a.time_limit_seconds, a.max_attempts,
      a.timezone, a.status,
      (SELECT count(*)::integer FROM edu.exam_items i
        WHERE i.workspace_id = a.workspace_id AND i.exam_version_id = a.exam_version_id),
      v.total_points::numeric,
      (SELECT count(*)::integer FROM edu.quiz_attempts q
        WHERE q.assignment_id = a.id AND q.student_id = s.id AND q.status <> 'void'),
      (SELECT q.id FROM edu.quiz_attempts q
        WHERE q.assignment_id = a.id AND q.student_id = s.id AND q.status = 'in_progress'),
      l.id, l.status, clock_timestamp()
    FROM edu.assignments a
    JOIN edu.students s ON s.workspace_id = a.workspace_id AND s.user_id = edu.actor_id()
      AND s.status = 'active'
    JOIN edu.workspaces w ON w.id = a.workspace_id AND w.is_active
    JOIN edu.enrollments e ON e.workspace_id = a.workspace_id AND e.class_id = a.class_id
      AND e.student_id = s.id AND e.status = 'active'
    JOIN edu.classes c ON c.workspace_id = a.workspace_id AND c.id = a.class_id
    JOIN edu.exam_versions v ON v.workspace_id = a.workspace_id AND v.id = a.exam_version_id
    LEFT JOIN LATERAL (
      SELECT q.id, q.status FROM edu.quiz_attempts q
      WHERE q.assignment_id = a.id AND q.student_id = s.id AND q.status <> 'void'
      ORDER BY q.attempt_no DESC LIMIT 1
    ) l ON true
    WHERE a.id = p_assignment_id AND a.status IN ('published','closed')
  $$;

-- Own attempt header (any enrollment state: retained history stays readable).
CREATE FUNCTION edu.student_attempt(p_attempt_id uuid)
  RETURNS TABLE(out_attempt_id uuid, out_assignment_id uuid, out_title text,
                out_attempt_no integer, out_status text, out_started_at timestamptz,
                out_deadline_at timestamptz, out_submitted_at timestamptz,
                out_submission_reason text, out_snapshot_sha256 bytea,
                out_answer_sequence integer, out_server_now timestamptz)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
    SELECT q.id, q.assignment_id, a.title, q.attempt_no, q.status, q.started_at, q.deadline_at,
      q.submitted_at, q.submission_reason, q.submitted_snapshot_sha256, q.answer_sequence,
      clock_timestamp()
    FROM edu.quiz_attempts q
    JOIN edu.assignments a ON a.workspace_id = q.workspace_id AND a.id = q.assignment_id
    WHERE q.id = p_attempt_id AND q.student_id = edu.assessment_actor_student(q.workspace_id)
  $$;

-- Items of the pinned version WITHOUT keys/explanations; choices rebuilt as {key,text} only.
CREATE FUNCTION edu.student_attempt_items(p_attempt_id uuid)
  RETURNS TABLE(out_item_id uuid, out_position integer, out_stem text, out_choices jsonb,
                out_points numeric, out_selected_key text, out_answer_revision integer,
                out_client_sequence bigint, out_saved_at timestamptz)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
    SELECT i.id, i.position::integer, i.stem::text,
      (SELECT coalesce(jsonb_agg(jsonb_build_object('key', c.value->>'key',
                                                    'text', c.value->>'text')
                                 ORDER BY c.ordinality), '[]'::jsonb)
       FROM jsonb_array_elements(i.choices) WITH ORDINALITY AS c(value, ordinality)),
      i.points::numeric, sa.response->>'selectedKey', coalesce(sa.answer_revision, 0),
      coalesce(sa.client_sequence, 0), sa.saved_at
    FROM edu.quiz_attempts q
    JOIN edu.exam_items i ON i.workspace_id = q.workspace_id
      AND i.exam_version_id = q.exam_version_id
    LEFT JOIN edu.student_answers sa ON sa.attempt_id = q.id AND sa.exam_item_id = i.id
    WHERE q.id = p_attempt_id AND q.student_id = edu.assessment_actor_student(q.workspace_id)
    ORDER BY i.position
  $$;
"""

STUDENT_WRITE_SQL = f"""
CREATE FUNCTION edu.student_start_attempt(p_assignment_id uuid, p_idempotency_key text,
    p_request_hash text)
  RETURNS TABLE(out_attempt_id uuid, out_created boolean, out_status text,
                out_attempt_no integer, out_started_at timestamptz,
                out_deadline_at timestamptz, out_server_now timestamptz)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
DECLARE
  actor uuid := edu.actor_id();
  asg edu.assignments%ROWTYPE;
  stu uuid;
  enr_status text;
  cls_status text;
  att edu.quiz_attempts%ROWTYPE;
  now_ts timestamptz;
  used integer;
  last_no integer;
BEGIN
  IF actor IS NULL THEN
    RAISE EXCEPTION 'Missing verified identity' USING ERRCODE = '28000';
  END IF;
  IF p_idempotency_key IS NULL OR length(p_idempotency_key) NOT BETWEEN 1 AND 200
     OR p_request_hash IS NULL OR length(p_request_hash) NOT BETWEEN 1 AND 128 THEN
    RAISE EXCEPTION 'Invalid idempotency key' USING ERRCODE = '22023';
  END IF;
  SELECT a.* INTO asg FROM edu.assignments a
    WHERE a.id = p_assignment_id AND a.status IN ('published','closed');
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Assignment not found' USING ERRCODE = 'P0002';
  END IF;
  stu := edu.assessment_actor_student(asg.workspace_id);
  IF stu IS NULL THEN
    RAISE EXCEPTION 'Assignment not found' USING ERRCODE = 'P0002';
  END IF;
  SELECT e.status INTO enr_status FROM edu.enrollments e
    WHERE e.workspace_id = asg.workspace_id AND e.class_id = asg.class_id
      AND e.student_id = stu;
  IF enr_status IS NULL THEN
    RAISE EXCEPTION 'Assignment not found' USING ERRCODE = 'P0002';
  END IF;
  -- Serialize start per (assignment, student); the partial unique index is the backstop.
  PERFORM pg_advisory_xact_lock(hashtext('edu.quiz_attempt:' || asg.id::text || ':'
                                         || stu::text));
  now_ts := clock_timestamp();
  SELECT q.* INTO att FROM edu.quiz_attempts q
    WHERE q.assignment_id = asg.id AND q.student_id = stu
      AND q.idempotency_key = p_idempotency_key;
  IF FOUND THEN
    IF att.request_hash <> p_request_hash THEN
      RAISE EXCEPTION 'Idempotency conflict' USING ERRCODE = 'EV011';
    END IF;
    RETURN QUERY SELECT att.id, false, att.status, att.attempt_no, att.started_at,
      att.deadline_at, now_ts;
    RETURN;
  END IF;
  -- An open attempt is returned whatever the key (deadline handling stays with submit/sweep).
  SELECT q.* INTO att FROM edu.quiz_attempts q
    WHERE q.assignment_id = asg.id AND q.student_id = stu AND q.status = 'in_progress';
  IF FOUND THEN
    RETURN QUERY SELECT att.id, false, att.status, att.attempt_no, att.started_at,
      att.deadline_at, now_ts;
    RETURN;
  END IF;
  SELECT c.status INTO cls_status FROM edu.classes c
    WHERE c.workspace_id = asg.workspace_id AND c.id = asg.class_id;
  IF enr_status <> 'active' OR cls_status <> 'active' OR asg.status <> 'published'
     OR now_ts < asg.opens_at OR (asg.closes_at IS NOT NULL AND now_ts >= asg.closes_at) THEN
    RAISE EXCEPTION 'Assignment unavailable' USING ERRCODE = 'EV012';
  END IF;
  SELECT count(*) FILTER (WHERE q.status <> 'void'), coalesce(max(q.attempt_no), 0)
    INTO used, last_no
    FROM edu.quiz_attempts q WHERE q.assignment_id = asg.id AND q.student_id = stu;
  IF used >= asg.max_attempts THEN
    RAISE EXCEPTION 'Attempt limit reached' USING ERRCODE = 'EV013';
  END IF;
  INSERT INTO edu.quiz_attempts(workspace_id, assignment_id, student_id, exam_version_id,
      attempt_no, status, started_at, deadline_at, idempotency_key, request_hash, updated_at)
    VALUES (asg.workspace_id, asg.id, stu, asg.exam_version_id, last_no + 1, 'in_progress',
      now_ts,
      LEAST(asg.closes_at, CASE WHEN asg.time_limit_seconds IS NULL THEN NULL
                                ELSE now_ts + asg.time_limit_seconds * interval '1 second' END),
      p_idempotency_key, p_request_hash, now_ts)
    RETURNING * INTO att;
  RETURN QUERY SELECT att.id, true, att.status, att.attempt_no, att.started_at,
    att.deadline_at, now_ts;
END $$;

CREATE FUNCTION edu.student_save_answer(p_attempt_id uuid, p_item_id uuid,
    p_selected_key text, p_expected_revision integer, p_client_sequence bigint)
  RETURNS TABLE(out_answer_revision integer, out_saved_at timestamptz,
                out_server_now timestamptz)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
DECLARE
  actor uuid := edu.actor_id();
  att edu.quiz_attempts%ROWTYPE;
  ans edu.student_answers%ROWTYPE;
  item_choices jsonb;
  now_ts timestamptz;
BEGIN
  IF actor IS NULL THEN
    RAISE EXCEPTION 'Missing verified identity' USING ERRCODE = '28000';
  END IF;
  IF p_client_sequence IS NULL OR p_client_sequence < 0
     OR p_expected_revision IS NULL OR p_expected_revision < 0 THEN
    RAISE EXCEPTION 'Invalid answer revision' USING ERRCODE = '22023';
  END IF;
  -- The attempt row lock serializes this write with submit and with the deadline sweeper.
  SELECT q.* INTO att FROM edu.quiz_attempts q
    WHERE q.id = p_attempt_id AND q.student_id = edu.assessment_actor_student(q.workspace_id)
    FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Attempt not found' USING ERRCODE = 'P0002';
  END IF;
  now_ts := clock_timestamp();
  IF att.status <> 'in_progress' THEN
    RAISE EXCEPTION 'Attempt is no longer in progress' USING ERRCODE = 'EV015';
  END IF;
  IF att.deadline_at IS NOT NULL AND now_ts > att.deadline_at + {GRACE} THEN
    RAISE EXCEPTION 'Attempt deadline passed' USING ERRCODE = 'EV010';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM edu.assignments a
    JOIN edu.classes c ON c.workspace_id = a.workspace_id AND c.id = a.class_id
    JOIN edu.enrollments e ON e.workspace_id = a.workspace_id AND e.class_id = a.class_id
    WHERE a.workspace_id = att.workspace_id AND a.id = att.assignment_id
      AND a.status IN ('published','closed') AND c.status = 'active'
      AND e.student_id = att.student_id AND e.status = 'active'
  ) THEN
    RAISE EXCEPTION 'Assignment unavailable' USING ERRCODE = 'EV012';
  END IF;
  SELECT i.choices INTO item_choices FROM edu.exam_items i
    WHERE i.workspace_id = att.workspace_id AND i.exam_version_id = att.exam_version_id
      AND i.id = p_item_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Item not found' USING ERRCODE = 'P0002';
  END IF;
  IF p_selected_key IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM jsonb_array_elements(item_choices) AS c(value)
    WHERE c.value->>'key' = p_selected_key
  ) THEN
    RAISE EXCEPTION 'Option is not part of the item' USING ERRCODE = 'EV016';
  END IF;
  SELECT sa.* INTO ans FROM edu.student_answers sa
    WHERE sa.attempt_id = att.id AND sa.exam_item_id = p_item_id FOR UPDATE;
  IF FOUND THEN
    IF p_client_sequence = ans.client_sequence
       AND p_expected_revision = ans.answer_revision - 1
       AND (ans.response->>'selectedKey') IS NOT DISTINCT FROM p_selected_key THEN
      -- Retry of a write that already committed: acknowledge it, write nothing.
      RETURN QUERY SELECT ans.answer_revision, ans.saved_at, now_ts;
      RETURN;
    END IF;
    IF p_client_sequence <= ans.client_sequence
       OR p_expected_revision <> ans.answer_revision THEN
      RAISE EXCEPTION 'Stale answer' USING ERRCODE = 'EV014';
    END IF;
    UPDATE edu.student_answers sa
      SET response = jsonb_build_object('selectedKey', p_selected_key),
          answer_revision = ans.answer_revision + 1, client_sequence = p_client_sequence,
          saved_at = now_ts
      WHERE sa.id = ans.id
      RETURNING sa.* INTO ans;
  ELSE
    IF p_expected_revision <> 0 THEN
      RAISE EXCEPTION 'Stale answer' USING ERRCODE = 'EV014';
    END IF;
    INSERT INTO edu.student_answers(workspace_id, attempt_id, exam_version_id, exam_item_id,
        response, answer_revision, client_sequence, saved_at)
      VALUES (att.workspace_id, att.id, att.exam_version_id, p_item_id,
        jsonb_build_object('selectedKey', p_selected_key), 1, p_client_sequence, now_ts)
      RETURNING * INTO ans;
  END IF;
  UPDATE edu.quiz_attempts q SET answer_sequence = q.answer_sequence + 1, updated_at = now_ts
    WHERE q.id = att.id;
  RETURN QUERY SELECT ans.answer_revision, ans.saved_at, now_ts;
END $$;

-- Idempotent submit. In progress -> finalize (reason 'deadline' once the grace has passed:
-- only answers saved before the deadline exist, and submitted_at is the deadline). Already
-- finalized -> no-op returning the same snapshot; reusing this submit key with a different
-- request hash is a conflict.
CREATE FUNCTION edu.student_submit(p_attempt_id uuid, p_idempotency_key text,
    p_request_hash text)
  RETURNS TABLE(out_status text, out_submitted_at timestamptz, out_snapshot_sha256 bytea,
                out_submission_reason text, out_job_id uuid, out_replayed boolean)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
DECLARE
  actor uuid := edu.actor_id();
  att edu.quiz_attempts%ROWTYPE;
  now_ts timestamptz;
  job uuid;
BEGIN
  IF actor IS NULL THEN
    RAISE EXCEPTION 'Missing verified identity' USING ERRCODE = '28000';
  END IF;
  IF p_idempotency_key IS NULL OR length(p_idempotency_key) NOT BETWEEN 1 AND 200
     OR p_request_hash IS NULL OR length(p_request_hash) NOT BETWEEN 1 AND 128 THEN
    RAISE EXCEPTION 'Invalid idempotency key' USING ERRCODE = '22023';
  END IF;
  SELECT q.* INTO att FROM edu.quiz_attempts q
    WHERE q.id = p_attempt_id AND q.student_id = edu.assessment_actor_student(q.workspace_id)
    FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Attempt not found' USING ERRCODE = 'P0002';
  END IF;
  now_ts := clock_timestamp();
  IF att.status = 'in_progress' THEN
    job := edu.finalize_attempt(att.id,
      CASE WHEN att.deadline_at IS NOT NULL AND now_ts > att.deadline_at + {GRACE}
           THEN 'deadline' ELSE 'student' END,
      now_ts, p_idempotency_key, p_request_hash);
    SELECT q.* INTO att FROM edu.quiz_attempts q WHERE q.id = p_attempt_id;
    RETURN QUERY SELECT att.status, att.submitted_at, att.submitted_snapshot_sha256,
      att.submission_reason, job, false;
    RETURN;
  END IF;
  IF att.status = 'void' THEN
    RAISE EXCEPTION 'Attempt is no longer in progress' USING ERRCODE = 'EV015';
  END IF;
  IF att.submit_idempotency_key = p_idempotency_key
     AND att.submit_request_hash IS DISTINCT FROM p_request_hash THEN
    RAISE EXCEPTION 'Idempotency conflict' USING ERRCODE = 'EV011';
  END IF;
  RETURN QUERY SELECT att.status, att.submitted_at, att.submitted_snapshot_sha256,
    att.submission_reason, NULL::uuid, true;
END $$;

-- Student feedback. Score only from a released grade revision; per-item correct keys and
-- explanations only after the assignment's solutions are released. Decimals are strings.
CREATE FUNCTION edu.student_results(p_attempt_id uuid) RETURNS jsonb
  LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
DECLARE
  actor uuid := edu.actor_id();
  att edu.quiz_attempts%ROWTYPE;
  asg edu.assignments%ROWTYPE;
  g edu.grades%ROWTYPE;
  released boolean;
  has_current boolean;
  solutions boolean;
  items jsonb := '[]'::jsonb;
BEGIN
  IF actor IS NULL THEN
    RAISE EXCEPTION 'Missing verified identity' USING ERRCODE = '28000';
  END IF;
  SELECT q.* INTO att FROM edu.quiz_attempts q
    WHERE q.id = p_attempt_id AND q.student_id = edu.assessment_actor_student(q.workspace_id);
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Attempt not found' USING ERRCODE = 'P0002';
  END IF;
  SELECT a.* INTO asg FROM edu.assignments a
    WHERE a.workspace_id = att.workspace_id AND a.id = att.assignment_id;
  SELECT gr.* INTO g FROM edu.grades gr
    WHERE gr.attempt_id = att.id AND gr.released_at IS NOT NULL
    ORDER BY gr.revision_no DESC LIMIT 1;
  released := FOUND;
  has_current := EXISTS (SELECT 1 FROM edu.grades gr WHERE gr.attempt_id = att.id
                         AND gr.is_current);
  solutions := asg.solutions_released_at IS NOT NULL AND att.status IN ('submitted','graded');
  IF att.status IN ('submitted','graded') AND solutions THEN
    SELECT coalesce(jsonb_agg(jsonb_build_object(
        'itemId', i.id, 'position', i.position, 'selectedKey', sa.response->>'selectedKey',
        'maxPoints', i.points::text,
        'awardedPoints', CASE WHEN released THEN gi.awarded_points::text END,
        'solution', jsonb_build_object('correctKey', btrim(k.correct_key::text),
                                       'explanation', k.explanation))
        ORDER BY i.position), '[]'::jsonb)
      INTO items
      FROM edu.exam_items i
      LEFT JOIN edu.student_answers sa ON sa.attempt_id = att.id AND sa.exam_item_id = i.id
      LEFT JOIN edu.grading_result_items gi ON released
        AND gi.grading_result_id = g.grading_result_id AND gi.exam_item_id = i.id
      LEFT JOIN edu.exam_answer_keys k ON k.exam_item_id = i.id
        AND k.workspace_id = i.workspace_id
      WHERE i.workspace_id = att.workspace_id AND i.exam_version_id = att.exam_version_id;
  ELSIF att.status IN ('submitted','graded') THEN
    SELECT coalesce(jsonb_agg(jsonb_build_object(
        'itemId', i.id, 'position', i.position, 'selectedKey', sa.response->>'selectedKey',
        'maxPoints', i.points::text,
        'awardedPoints', CASE WHEN released THEN gi.awarded_points::text END,
        'solution', NULL)
        ORDER BY i.position), '[]'::jsonb)
      INTO items
      FROM edu.exam_items i
      LEFT JOIN edu.student_answers sa ON sa.attempt_id = att.id AND sa.exam_item_id = i.id
      LEFT JOIN edu.grading_result_items gi ON released
        AND gi.grading_result_id = g.grading_result_id AND gi.exam_item_id = i.id
      WHERE i.workspace_id = att.workspace_id AND i.exam_version_id = att.exam_version_id;
  END IF;
  RETURN jsonb_build_object(
    'attemptId', att.id, 'assignmentId', att.assignment_id, 'status', att.status,
    'submittedAt', att.submitted_at,
    'gradingStatus', CASE WHEN att.status = 'in_progress' THEN 'not_submitted'
                          WHEN att.status = 'void' THEN 'void'
                          WHEN has_current THEN 'graded' ELSE 'pending' END,
    'scoreReleased', released,
    'score', CASE WHEN released THEN g.score::text END,
    'maxScore', CASE WHEN released THEN g.max_score::text END,
    'releasedAt', CASE WHEN released THEN g.released_at END,
    'solutionsReleased', solutions,
    'items', items);
END $$;
"""

SYSTEM_SQL = f"""
-- Deadline sweeper (cross-tenant, returns ids only). A caller-supplied time can never be in
-- the future, so it cannot expire attempts early. Rows locked by a concurrent save/submit are
-- skipped and picked up by the next sweep; finalize_attempt re-checks the status under lock.
CREATE FUNCTION edu.expire_attempts(p_now timestamptz)
  RETURNS TABLE(out_attempt_id uuid, out_workspace_id uuid, out_job_id uuid)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
DECLARE
  eff timestamptz := LEAST(coalesce(p_now, clock_timestamp()), clock_timestamp());
  r record;
BEGIN
  FOR r IN SELECT q.id, q.workspace_id FROM edu.quiz_attempts q
    WHERE q.status = 'in_progress' AND q.deadline_at IS NOT NULL
      AND q.deadline_at + {GRACE} < eff
    ORDER BY q.deadline_at LIMIT 500 FOR UPDATE SKIP LOCKED
  LOOP
    out_job_id := edu.finalize_attempt(r.id, 'deadline', clock_timestamp(), NULL, NULL);
    out_attempt_id := r.id;
    out_workspace_id := r.workspace_id;
    RETURN NEXT;
  END LOOP;
END $$;

-- after_close releases. Scores: stamp the assignment and every current unreleased grade.
-- Solutions: only once no attempt of the assignment is still in progress.
CREATE FUNCTION edu.apply_due_releases(p_now timestamptz)
  RETURNS TABLE(out_assignment_id uuid, out_kind text)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
DECLARE
  eff timestamptz := LEAST(coalesce(p_now, clock_timestamp()), clock_timestamp());
  r record;
BEGIN
  FOR r IN SELECT a.id, a.workspace_id FROM edu.assignments a
    WHERE a.score_release = 'after_close' AND a.scores_released_at IS NULL
      AND a.status IN ('published','closed') AND a.closes_at <= eff
    ORDER BY a.closes_at LIMIT 200 FOR UPDATE SKIP LOCKED
  LOOP
    UPDATE edu.assignments a SET scores_released_at = eff, updated_at = clock_timestamp()
      WHERE a.id = r.id;
    UPDATE edu.grades g SET released_at = eff
      FROM edu.quiz_attempts q
      WHERE q.id = g.attempt_id AND q.workspace_id = r.workspace_id AND q.assignment_id = r.id
        AND g.is_current AND g.released_at IS NULL;
    out_assignment_id := r.id;
    out_kind := 'scores';
    RETURN NEXT;
  END LOOP;
  FOR r IN SELECT a.id FROM edu.assignments a
    WHERE a.solution_release = 'after_close' AND a.solutions_released_at IS NULL
      AND a.status IN ('published','closed') AND a.closes_at <= eff
      AND NOT EXISTS (SELECT 1 FROM edu.quiz_attempts q
                      WHERE q.assignment_id = a.id AND q.status = 'in_progress')
    ORDER BY a.closes_at LIMIT 200 FOR UPDATE SKIP LOCKED
  LOOP
    UPDATE edu.assignments a SET solutions_released_at = eff, updated_at = clock_timestamp()
      WHERE a.id = r.id;
    out_assignment_id := r.id;
    out_kind := 'solutions';
    RETURN NEXT;
  END LOOP;
END $$;
"""

PUBLIC_FUNCTIONS = (
    "edu.student_assignments()",
    "edu.student_assignment_detail(uuid)",
    "edu.student_attempt(uuid)",
    "edu.student_attempt_items(uuid)",
    "edu.student_start_attempt(uuid, text, text)",
    "edu.student_save_answer(uuid, uuid, text, integer, bigint)",
    "edu.student_submit(uuid, text, text)",
    "edu.student_results(uuid)",
    "edu.expire_attempts(timestamptz)",
    "edu.apply_due_releases(timestamptz)",
)


def upgrade():
    op.execute(TABLES_SQL)
    op.execute(GUARDS_SQL)
    for table in TENANT_TABLES:
        op.execute(f"""
        ALTER TABLE edu.{table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE edu.{table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {table}_tenant ON edu.{table} FOR ALL
          USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
        """)
    op.execute(OWNER_ACCESS_SQL)
    op.execute(HELPERS_SQL)
    op.execute(STUDENT_READ_SQL)
    op.execute(STUDENT_WRITE_SQL)
    op.execute(SYSTEM_SQL)
    owners = "\n".join(
        f"ALTER FUNCTION {signature} OWNER TO eduvia_identity_owner;"
        for signature in PUBLIC_FUNCTIONS
    )
    op.execute(f"""
    {owners}
    REVOKE ALL ON FUNCTION {", ".join(PUBLIC_FUNCTIONS)} FROM PUBLIC;
    REVOKE CREATE ON SCHEMA edu FROM eduvia_identity_owner;
    """)
    op.execute(f"""
    DO $$ BEGIN
      IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduvia_runtime') THEN
        -- Default privileges grant more; replace them with the exact lean set.
        REVOKE ALL ON edu.assignments, edu.quiz_attempts, edu.student_answers,
          edu.grading_results, edu.grading_result_items, edu.grades FROM eduvia_runtime;
        GRANT SELECT, INSERT, UPDATE ON edu.assignments, edu.quiz_attempts,
          edu.student_answers TO eduvia_runtime;
        -- Grading evidence is append-only.
        GRANT SELECT, INSERT ON edu.grading_results, edu.grading_result_items
          TO eduvia_runtime;
        -- Grades: UPDATE only for the guarded is_current flip and the one-way release stamp.
        GRANT SELECT, INSERT, UPDATE ON edu.grades TO eduvia_runtime;
        GRANT EXECUTE ON FUNCTION {", ".join(PUBLIC_FUNCTIONS)} TO eduvia_runtime;
      END IF;
    END $$;
    """)


def downgrade():
    raise RuntimeError("Assessment migration is forward-only; restore a reviewed backup instead")
