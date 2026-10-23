"""PILOT-05 privacy: guardian consent, consent links, export/erasure requests and the consent gate
on attempt start.

Legal assumptions are pending review (tasks/decisions/0008-privacy-consent-retention.md); every
threshold is a parameter supplied by the API from settings, never hard-coded policy:

* ``edu.students`` gains ``birth_year`` (year only, self-declared once by the student),
  ``consent_status`` (unknown | not_required | pending | granted | revoked) and ``erased_at``.
  Age is the conservative lower bound ``current year (Asia/Ho_Chi_Minh) - birth_year - 1``.
* ``student_consents`` is append-only: identity, method, policy version and ``granted_at`` are
  immutable; the only updates are a one-time revocation and scrubbing personal fields to NULL
  on erasure. A trigger keeps ``students.consent_status`` in sync (any active row -> granted,
  otherwise revoked). The guardian contact is stored only as a sha256 digest of the normalised
  email/phone; the plaintext never reaches the database.
* ``consent_links`` mirror class invitations: sha256 token digest, at most 30 days, single use.
  ``edu.guardian_consent_by_link`` needs no actor (the guardian has no account).
* ``privacy_requests`` track export/erasure jobs (queued -> succeeded | failed | rejected).
* Every new table is tenant-owned with FORCE RLS; the runtime role gets SELECT/INSERT/UPDATE only
  (no DELETE). Student and public operations go through SECURITY DEFINER functions owned by the
  NOLOGIN ``eduvia_identity_owner``.
* Gate: ``edu.student_start_attempt(uuid, text, text, integer)`` raises EV017 when consent is
  required (status unknown/pending/revoked AND birth year unknown or below the consent age).
  The 0015 three-argument signature is kept as a wrapper using 16.
* Error codes: P0002 not found, 28000 no identity, 22023 invalid argument, EV017 consent
  required, EV018 consent link unavailable (used/expired/erased), EV019 birth year already
  recorded with a different value.
"""

from alembic import op

revision = "0016_privacy_consent"
down_revision = "0015_assessment"
branch_labels = None
depends_on = None

TENANT_TABLES = ("student_consents", "consent_links", "privacy_requests")

TENANT_PREDICATE = (
    "workspace_id::text = current_setting('edu.current_workspace_id', true) "
    "AND edu.can_read_workspace(workspace_id)"
)

# Lower-bound age from a birth year (the birthday may not have passed yet this year).
LOCAL_YEAR = "extract(year FROM clock_timestamp() AT TIME ZONE 'Asia/Ho_Chi_Minh')::integer"

STUDENTS_SQL = """
ALTER TABLE edu.students
  ADD COLUMN birth_year smallint
    CHECK (birth_year IS NULL OR birth_year BETWEEN 1900 AND 2100),
  ADD COLUMN consent_status text NOT NULL DEFAULT 'unknown'
    CHECK (consent_status IN ('unknown','not_required','pending','granted','revoked')),
  ADD COLUMN erased_at timestamptz;
CREATE INDEX ix_students_workspace_consent ON edu.students(workspace_id, consent_status);
"""

TABLES_SQL = """
CREATE TABLE edu.student_consents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
  student_id uuid NOT NULL,
  method text NOT NULL CHECK (method IN ('paper_school','guardian_link','self_adult')),
  policy_version text NOT NULL CHECK (length(policy_version) BETWEEN 1 AND 32),
  guardian_name text
    CHECK (guardian_name IS NULL OR length(btrim(guardian_name)) BETWEEN 1 AND 200),
  guardian_contact_hash bytea
    CHECK (guardian_contact_hash IS NULL OR octet_length(guardian_contact_hash) = 32),
  recorded_by_user_id uuid REFERENCES edu.users(id),
  granted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  revoked_at timestamptz,
  revoke_reason text CHECK (revoke_reason IS NULL OR length(revoke_reason) BETWEEN 1 AND 500),
  evidence_note text CHECK (evidence_note IS NULL OR length(evidence_note) <= 500),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_student_consents_workspace_id UNIQUE (workspace_id, id),
  CONSTRAINT fk_student_consents_student FOREIGN KEY (workspace_id, student_id)
    REFERENCES edu.students(workspace_id, id),
  CONSTRAINT ck_student_consents_recorder
    CHECK (method = 'guardian_link' OR recorded_by_user_id IS NOT NULL),
  CONSTRAINT ck_student_consents_revoked CHECK (revoked_at IS NULL OR revoked_at >= granted_at)
);
CREATE INDEX ix_student_consents_student ON edu.student_consents(workspace_id, student_id);

CREATE TABLE edu.consent_links (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
  student_id uuid NOT NULL,
  token_hash bytea NOT NULL,
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  created_by_user_id uuid NOT NULL REFERENCES edu.users(id),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_consent_links_token_hash UNIQUE (token_hash),
  CONSTRAINT uq_consent_links_workspace_id UNIQUE (workspace_id, id),
  CONSTRAINT fk_consent_links_student FOREIGN KEY (workspace_id, student_id)
    REFERENCES edu.students(workspace_id, id),
  CONSTRAINT ck_consent_links_token_hash CHECK (octet_length(token_hash) = 32),
  CONSTRAINT ck_consent_links_expiry CHECK (
    expires_at > created_at AND expires_at <= created_at + interval '30 days 1 hour')
);
CREATE INDEX ix_consent_links_student ON edu.consent_links(workspace_id, student_id);

CREATE TABLE edu.privacy_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
  student_id uuid,
  user_id uuid REFERENCES edu.users(id),
  kind text NOT NULL CHECK (kind IN ('export','erasure')),
  status text NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued','succeeded','failed','rejected')),
  requested_by_user_id uuid NOT NULL REFERENCES edu.users(id),
  background_job_id uuid,
  object_key text CHECK (object_key IS NULL OR length(object_key) BETWEEN 1 AND 300),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  finished_at timestamptz,
  note text CHECK (note IS NULL OR length(note) <= 500),
  CONSTRAINT uq_privacy_requests_workspace_id UNIQUE (workspace_id, id),
  CONSTRAINT fk_privacy_requests_student FOREIGN KEY (workspace_id, student_id)
    REFERENCES edu.students(workspace_id, id),
  CONSTRAINT fk_privacy_requests_job FOREIGN KEY (workspace_id, background_job_id)
    REFERENCES edu.background_jobs(workspace_id, id),
  CONSTRAINT ck_privacy_requests_subject CHECK ((student_id IS NULL) <> (user_id IS NULL)),
  CONSTRAINT ck_privacy_requests_self CHECK (user_id IS NULL OR user_id = requested_by_user_id),
  CONSTRAINT ck_privacy_requests_finished CHECK ((status = 'queued') = (finished_at IS NULL)),
  CONSTRAINT ck_privacy_requests_object CHECK (
    object_key IS NULL OR (kind = 'export' AND status = 'succeeded' AND (
      object_key = 'ws/' || workspace_id::text || '/privacy/' || id::text || '.json'
      OR object_key = 'users/' || user_id::text || '/privacy/' || id::text || '.json')))
);
CREATE UNIQUE INDEX uq_privacy_requests_job ON edu.privacy_requests(background_job_id)
  WHERE background_job_id IS NOT NULL;
CREATE INDEX ix_privacy_requests_student ON edu.privacy_requests(workspace_id, student_id);
"""

# Invoker triggers: they run as the caller (runtime role under RLS, or the definer owner).
GUARDS_SQL = """
CREATE FUNCTION edu.student_consent_guard() RETURNS trigger
  LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
  BEGIN
    IF TG_OP = 'INSERT' THEN
      IF NEW.revoked_at IS NOT NULL OR NEW.revoke_reason IS NOT NULL THEN
        RAISE EXCEPTION 'consents start active' USING ERRCODE = 'check_violation';
      END IF;
      IF EXISTS (SELECT 1 FROM edu.students s WHERE s.workspace_id = NEW.workspace_id
                 AND s.id = NEW.student_id AND s.erased_at IS NOT NULL) THEN
        RAISE EXCEPTION 'student was erased' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END IF;
    IF (NEW.id, NEW.workspace_id, NEW.student_id, NEW.method, NEW.policy_version,
        NEW.recorded_by_user_id, NEW.granted_at, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.workspace_id, OLD.student_id, OLD.method, OLD.policy_version,
        OLD.recorded_by_user_id, OLD.granted_at, OLD.created_at) THEN
      RAISE EXCEPTION 'consent records are append-only' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.revoked_at IS NOT NULL AND (NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
        OR NEW.revoke_reason IS DISTINCT FROM OLD.revoke_reason) THEN
      RAISE EXCEPTION 'consent revocation is final' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.revoked_at IS NULL AND NEW.revoke_reason IS NOT NULL THEN
      RAISE EXCEPTION 'revoke reason needs a revocation' USING ERRCODE = 'check_violation';
    END IF;
    -- Personal fields may only be scrubbed (erasure), never rewritten.
    IF (NEW.guardian_name IS NOT NULL AND NEW.guardian_name IS DISTINCT FROM OLD.guardian_name)
       OR (NEW.guardian_contact_hash IS NOT NULL
           AND NEW.guardian_contact_hash IS DISTINCT FROM OLD.guardian_contact_hash)
       OR (NEW.evidence_note IS NOT NULL AND NEW.evidence_note IS DISTINCT FROM OLD.evidence_note)
    THEN
      RAISE EXCEPTION 'consent details can only be scrubbed' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END $$;
CREATE TRIGGER student_consent_guard BEFORE INSERT OR UPDATE ON edu.student_consents
  FOR EACH ROW EXECUTE FUNCTION edu.student_consent_guard();

-- Any active consent row -> granted; the last one revoked -> revoked.
CREATE FUNCTION edu.student_consent_sync() RETURNS trigger
  LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
  BEGIN
    UPDATE edu.students s SET consent_status = CASE
        WHEN EXISTS (SELECT 1 FROM edu.student_consents c
                     WHERE c.workspace_id = NEW.workspace_id AND c.student_id = NEW.student_id
                       AND c.revoked_at IS NULL) THEN 'granted'
        ELSE 'revoked' END,
      updated_at = clock_timestamp()
      WHERE s.workspace_id = NEW.workspace_id AND s.id = NEW.student_id;
    RETURN NULL;
  END $$;
CREATE TRIGGER student_consent_sync AFTER INSERT OR UPDATE OF revoked_at
  ON edu.student_consents FOR EACH ROW EXECUTE FUNCTION edu.student_consent_sync();

CREATE FUNCTION edu.privacy_request_guard() RETURNS trigger
  LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
  BEGIN
    IF (NEW.id, NEW.workspace_id, NEW.student_id, NEW.user_id, NEW.kind,
        NEW.requested_by_user_id, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.workspace_id, OLD.student_id, OLD.user_id, OLD.kind,
        OLD.requested_by_user_id, OLD.created_at) THEN
      RAISE EXCEPTION 'privacy request identity is immutable' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.background_job_id IS NOT NULL
       AND NEW.background_job_id IS DISTINCT FROM OLD.background_job_id THEN
      RAISE EXCEPTION 'privacy request job is immutable' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status <> 'queued' AND (NEW.status IS DISTINCT FROM OLD.status
        OR NEW.finished_at IS DISTINCT FROM OLD.finished_at) THEN
      RAISE EXCEPTION 'finished privacy request is final' USING ERRCODE = 'check_violation';
    END IF;
    -- The export object can be recorded when the request succeeds and later only purged.
    IF NEW.object_key IS NOT NULL AND NEW.object_key IS DISTINCT FROM OLD.object_key
       AND OLD.status <> 'queued' THEN
      RAISE EXCEPTION 'export object can only be purged' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END $$;
CREATE TRIGGER privacy_request_guard BEFORE UPDATE ON edu.privacy_requests
  FOR EACH ROW EXECUTE FUNCTION edu.privacy_request_guard();

REVOKE ALL ON FUNCTION edu.student_consent_guard(), edu.student_consent_sync(),
  edu.privacy_request_guard() FROM PUBLIC;
"""

OWNER_ACCESS_SQL = """
GRANT CREATE ON SCHEMA edu TO eduvia_identity_owner;
GRANT SELECT, INSERT, UPDATE ON edu.student_consents TO eduvia_identity_owner;
GRANT SELECT, UPDATE ON edu.consent_links TO eduvia_identity_owner;
CREATE POLICY student_consents_privacy_function ON edu.student_consents
  TO eduvia_identity_owner USING (true) WITH CHECK (true);
CREATE POLICY consent_links_privacy_function ON edu.consent_links
  TO eduvia_identity_owner USING (true) WITH CHECK (true);
"""

# Internal helpers: owned by the definer role, revoked from PUBLIC and never granted to the
# runtime role; they execute only inside the SECURITY DEFINER functions below.
HELPERS_SQL = f"""
CREATE FUNCTION edu.privacy_min_age(p_birth_year integer) RETURNS integer
  LANGUAGE sql STABLE SET search_path=pg_catalog,edu AS $$
    SELECT CASE WHEN p_birth_year IS NULL THEN NULL
                ELSE {LOCAL_YEAR} - p_birth_year - 1 END
  $$;

-- Mirrored by app.services.privacy.consent_required.
CREATE FUNCTION edu.privacy_consent_required(p_status text, p_birth_year integer,
    p_consent_age integer) RETURNS boolean
  LANGUAGE sql STABLE SET search_path=pg_catalog,edu AS $$
    SELECT p_status IN ('unknown','pending','revoked')
      AND (p_birth_year IS NULL OR edu.privacy_min_age(p_birth_year) < p_consent_age)
  $$;

-- The verified actor's staff role in the CURRENT workspace context (NULL otherwise).
CREATE FUNCTION edu.privacy_staff_role(p_workspace_id uuid) RETURNS text
  LANGUAGE sql STABLE SET search_path=pg_catalog,edu AS $$
    SELECT m.role::text FROM edu.workspace_members m
    JOIN edu.workspaces w ON w.id = m.workspace_id AND w.is_active
    WHERE m.workspace_id = p_workspace_id AND m.user_id = edu.actor_id()
      AND m.status = 'active' AND m.role IN ('owner','admin','teacher')
      AND p_workspace_id::text = current_setting('edu.current_workspace_id', true)
  $$;

-- One student's own data. Never answer keys, explanations or other students' rows; only
-- released grade revisions.
CREATE FUNCTION edu.privacy_student_payload(p_student_id uuid) RETURNS jsonb
  LANGUAGE sql STABLE SET search_path=pg_catalog,edu AS $$
    SELECT jsonb_build_object(
      'studentId', s.id, 'workspaceId', s.workspace_id, 'workspaceName', w.name,
      'displayName', s.display_name, 'externalCode', s.external_code,
      'birthYear', s.birth_year, 'consentStatus', s.consent_status, 'status', s.status,
      'createdAt', s.created_at, 'erasedAt', s.erased_at,
      'enrollments', (
        SELECT coalesce(jsonb_agg(jsonb_build_object(
            'classId', c.id, 'className', c.name, 'status', e.status,
            'joinedAt', e.joined_at, 'withdrawnAt', e.withdrawn_at) ORDER BY e.created_at),
          '[]'::jsonb)
        FROM edu.enrollments e
        JOIN edu.classes c ON c.workspace_id = e.workspace_id AND c.id = e.class_id
        WHERE e.workspace_id = s.workspace_id AND e.student_id = s.id),
      'consents', (
        SELECT coalesce(jsonb_agg(jsonb_build_object(
            'id', k.id, 'method', k.method, 'policyVersion', k.policy_version,
            'guardianName', k.guardian_name, 'grantedAt', k.granted_at,
            'revokedAt', k.revoked_at, 'revokeReason', k.revoke_reason)
            ORDER BY k.granted_at), '[]'::jsonb)
        FROM edu.student_consents k
        WHERE k.workspace_id = s.workspace_id AND k.student_id = s.id),
      'attempts', (
        SELECT coalesce(jsonb_agg(jsonb_build_object(
            'attemptId', q.id, 'assignmentId', q.assignment_id, 'assignmentTitle', a.title,
            'attemptNo', q.attempt_no, 'status', q.status, 'startedAt', q.started_at,
            'submittedAt', q.submitted_at,
            'answers', (
              SELECT coalesce(jsonb_agg(jsonb_build_object(
                  'itemId', sa.exam_item_id, 'selectedKey', sa.response->>'selectedKey',
                  'savedAt', sa.saved_at) ORDER BY sa.exam_item_id), '[]'::jsonb)
              FROM edu.student_answers sa
              WHERE sa.workspace_id = q.workspace_id AND sa.attempt_id = q.id),
            'releasedGrade', (
              SELECT jsonb_build_object('score', g.score::text, 'maxScore', g.max_score::text,
                                        'releasedAt', g.released_at)
              FROM edu.grades g
              WHERE g.workspace_id = q.workspace_id AND g.attempt_id = q.id
                AND g.released_at IS NOT NULL
              ORDER BY g.revision_no DESC LIMIT 1))
            ORDER BY q.started_at, q.id), '[]'::jsonb)
        FROM edu.quiz_attempts q
        JOIN edu.assignments a ON a.workspace_id = q.workspace_id AND a.id = q.assignment_id
        WHERE q.workspace_id = s.workspace_id AND q.student_id = s.id))
    FROM edu.students s JOIN edu.workspaces w ON w.id = s.workspace_id
    WHERE s.id = p_student_id
  $$;

-- Pseudonymise one student row; attempts/answers/grades stay and keep pointing at it.
-- Returns 1 when erased now, 0 when it was already erased (idempotent replay).
CREATE FUNCTION edu.privacy_erase_student_row(p_student_id uuid) RETURNS integer
  LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
  BEGIN
    PERFORM 1 FROM edu.students s WHERE s.id = p_student_id AND s.erased_at IS NULL
      FOR UPDATE;
    IF NOT FOUND THEN
      RETURN 0;
    END IF;
    UPDATE edu.student_consents c
      SET revoked_at = coalesce(c.revoked_at, clock_timestamp()),
          revoke_reason = coalesce(c.revoke_reason, 'erased'),
          guardian_name = NULL, guardian_contact_hash = NULL, evidence_note = NULL
      WHERE c.student_id = p_student_id;
    UPDATE edu.consent_links l SET used_at = clock_timestamp()
      WHERE l.student_id = p_student_id AND l.used_at IS NULL;
    UPDATE edu.enrollments e SET status = 'withdrawn', withdrawn_at = clock_timestamp(),
      updated_at = clock_timestamp()
      WHERE e.student_id = p_student_id AND e.status <> 'withdrawn';
    UPDATE edu.students s SET display_name = 'Học sinh đã xóa', external_code = NULL,
      user_id = NULL, birth_year = NULL, consent_status = 'revoked', status = 'inactive',
      erased_at = clock_timestamp(), updated_at = clock_timestamp()
      WHERE s.id = p_student_id;
    RETURN 1;
  END $$;
"""

FUNCTIONS_SQL = f"""
CREATE FUNCTION edu.student_set_birth_year(p_year integer, p_consent_age integer)
  RETURNS TABLE(out_workspace_id uuid, out_student_id uuid, out_consent_status text,
                out_consent_required boolean)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
DECLARE
  actor uuid := edu.actor_id();
  r record;
  next_status text;
BEGIN
  IF actor IS NULL THEN
    RAISE EXCEPTION 'Missing verified identity' USING ERRCODE = '28000';
  END IF;
  IF p_consent_age IS NULL OR p_consent_age NOT BETWEEN 12 AND 18
     OR p_year IS NULL OR p_year < 1900 OR p_year > {LOCAL_YEAR} THEN
    RAISE EXCEPTION 'Invalid birth year' USING ERRCODE = '22023';
  END IF;
  FOR r IN SELECT s.id, s.workspace_id, s.birth_year, s.consent_status
    FROM edu.students s JOIN edu.workspaces w ON w.id = s.workspace_id AND w.is_active
    WHERE s.user_id = actor AND s.erased_at IS NULL
    ORDER BY s.created_at, s.id FOR UPDATE OF s
  LOOP
    IF r.birth_year IS NOT NULL AND r.birth_year <> p_year THEN
      RAISE EXCEPTION 'Birth year already recorded' USING ERRCODE = 'EV019';
    END IF;
    next_status := CASE
      WHEN edu.privacy_min_age(p_year) >= p_consent_age THEN 'not_required'
      WHEN r.consent_status IN ('granted','revoked') THEN r.consent_status
      ELSE 'pending' END;
    UPDATE edu.students s SET birth_year = p_year, consent_status = next_status,
      updated_at = clock_timestamp() WHERE s.id = r.id;
    out_workspace_id := r.workspace_id;
    out_student_id := r.id;
    out_consent_status := next_status;
    out_consent_required := edu.privacy_consent_required(next_status, p_year, p_consent_age);
    RETURN NEXT;
  END LOOP;
END $$;

CREATE FUNCTION edu.student_consent_status(p_consent_age integer)
  RETURNS TABLE(out_workspace_id uuid, out_workspace_name text, out_student_id uuid,
                out_class_name text, out_birth_year integer, out_consent_status text,
                out_consent_required boolean)
  LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
DECLARE
  actor uuid := edu.actor_id();
BEGIN
  IF actor IS NULL THEN
    RAISE EXCEPTION 'Missing verified identity' USING ERRCODE = '28000';
  END IF;
  IF p_consent_age IS NULL OR p_consent_age NOT BETWEEN 12 AND 18 THEN
    RAISE EXCEPTION 'Invalid consent age' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY SELECT s.workspace_id, w.name::text, s.id,
    (SELECT c.name::text FROM edu.enrollments e
      JOIN edu.classes c ON c.workspace_id = e.workspace_id AND c.id = e.class_id
      WHERE e.workspace_id = s.workspace_id AND e.student_id = s.id AND e.status = 'active'
      ORDER BY e.joined_at DESC NULLS LAST, c.id LIMIT 1),
    s.birth_year::integer, s.consent_status,
    edu.privacy_consent_required(s.consent_status, s.birth_year, p_consent_age)
  FROM edu.students s JOIN edu.workspaces w ON w.id = s.workspace_id AND w.is_active
  WHERE s.user_id = actor AND s.status = 'active' AND s.erased_at IS NULL
  ORDER BY w.name, s.id;
END $$;

-- Public (no account): what the guardian sees before agreeing. Given name only.
CREATE FUNCTION edu.consent_link_info(p_token_hash bytea)
  RETURNS TABLE(out_student_given_name text, out_workspace_name text,
                out_expires_at timestamptz)
  LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
DECLARE
  l edu.consent_links%ROWTYPE;
  stu edu.students%ROWTYPE;
  ws edu.workspaces%ROWTYPE;
BEGIN
  SELECT * INTO l FROM edu.consent_links c WHERE c.token_hash = p_token_hash;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Consent link not found' USING ERRCODE = 'P0002';
  END IF;
  SELECT * INTO stu FROM edu.students s
    WHERE s.workspace_id = l.workspace_id AND s.id = l.student_id;
  SELECT * INTO ws FROM edu.workspaces w WHERE w.id = l.workspace_id;
  IF l.used_at IS NOT NULL OR l.expires_at <= clock_timestamp() OR stu.erased_at IS NOT NULL
     OR NOT ws.is_active THEN
    RAISE EXCEPTION 'Consent link unavailable' USING ERRCODE = 'EV018';
  END IF;
  RETURN QUERY SELECT regexp_replace(btrim(stu.display_name), '^.*\\s', ''),
    ws.name::text, l.expires_at;
END $$;

-- Public (no account): single-use guardian consent. The link row lock serializes concurrent
-- submissions so exactly one consent is recorded.
CREATE FUNCTION edu.guardian_consent_by_link(p_token_hash bytea, p_guardian_name text,
    p_contact_hash bytea, p_policy_version text)
  RETURNS TABLE(out_consent_id uuid, out_workspace_id uuid, out_student_id uuid)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
DECLARE
  l edu.consent_links%ROWTYPE;
  stu edu.students%ROWTYPE;
  consent uuid;
BEGIN
  IF p_guardian_name IS NULL OR length(btrim(p_guardian_name)) NOT BETWEEN 1 AND 200
     OR p_contact_hash IS NULL OR octet_length(p_contact_hash) <> 32
     OR p_policy_version IS NULL OR length(p_policy_version) NOT BETWEEN 1 AND 32 THEN
    RAISE EXCEPTION 'Invalid consent' USING ERRCODE = '22023';
  END IF;
  SELECT * INTO l FROM edu.consent_links c WHERE c.token_hash = p_token_hash FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Consent link not found' USING ERRCODE = 'P0002';
  END IF;
  IF l.used_at IS NOT NULL OR l.expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'Consent link unavailable' USING ERRCODE = 'EV018';
  END IF;
  SELECT * INTO stu FROM edu.students s
    WHERE s.workspace_id = l.workspace_id AND s.id = l.student_id FOR UPDATE;
  IF stu.erased_at IS NOT NULL OR NOT EXISTS (
      SELECT 1 FROM edu.workspaces w WHERE w.id = l.workspace_id AND w.is_active) THEN
    RAISE EXCEPTION 'Consent link unavailable' USING ERRCODE = 'EV018';
  END IF;
  INSERT INTO edu.student_consents(workspace_id, student_id, method, policy_version,
      guardian_name, guardian_contact_hash)
    VALUES (l.workspace_id, l.student_id, 'guardian_link', p_policy_version,
      btrim(p_guardian_name), p_contact_hash)
    RETURNING id INTO consent;
  UPDATE edu.consent_links c SET used_at = clock_timestamp() WHERE c.id = l.id;
  RETURN QUERY SELECT consent, l.workspace_id, l.student_id;
END $$;

-- Staff erasure inside the student's workspace context.
CREATE FUNCTION edu.erase_student(p_student_id uuid) RETURNS integer
  LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
DECLARE
  actor uuid := edu.actor_id();
  ws uuid;
BEGIN
  IF actor IS NULL THEN
    RAISE EXCEPTION 'Missing verified identity' USING ERRCODE = '28000';
  END IF;
  SELECT s.workspace_id INTO ws FROM edu.students s WHERE s.id = p_student_id;
  IF ws IS NULL OR edu.privacy_staff_role(ws) IS NULL THEN
    RAISE EXCEPTION 'Student not found' USING ERRCODE = 'P0002';
  END IF;
  RETURN edu.privacy_erase_student_row(p_student_id);
END $$;

-- Self-service erasure: pseudonymise the actor, every student row and revoke memberships.
CREATE FUNCTION edu.erase_self() RETURNS uuid
  LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
DECLARE
  actor uuid := edu.actor_id();
  r record;
BEGIN
  IF actor IS NULL THEN
    RAISE EXCEPTION 'Missing verified identity' USING ERRCODE = '28000';
  END IF;
  FOR r IN SELECT s.id FROM edu.students s WHERE s.user_id = actor ORDER BY s.id LOOP
    PERFORM edu.privacy_erase_student_row(r.id);
  END LOOP;
  UPDATE edu.workspace_members m SET status = 'revoked', updated_at = clock_timestamp()
    WHERE m.user_id = actor AND m.status <> 'revoked';
  UPDATE edu.users u SET email = 'erased+' || u.id::text || '@invalid',
    display_name = 'Người dùng đã xóa', is_active = false, updated_at = clock_timestamp()
    WHERE u.id = actor;
  RETURN actor;
END $$;

CREATE FUNCTION edu.student_export(p_student_id uuid) RETURNS jsonb
  LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
DECLARE
  actor uuid := edu.actor_id();
  ws uuid;
BEGIN
  IF actor IS NULL THEN
    RAISE EXCEPTION 'Missing verified identity' USING ERRCODE = '28000';
  END IF;
  SELECT s.workspace_id INTO ws FROM edu.students s WHERE s.id = p_student_id;
  IF ws IS NULL OR edu.privacy_staff_role(ws) IS NULL THEN
    RAISE EXCEPTION 'Student not found' USING ERRCODE = 'P0002';
  END IF;
  RETURN jsonb_build_object('kind', 'student_export', 'generatedAt', clock_timestamp(),
    'student', edu.privacy_student_payload(p_student_id));
END $$;

CREATE FUNCTION edu.self_export() RETURNS jsonb
  LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
DECLARE
  actor uuid := edu.actor_id();
  u edu.users%ROWTYPE;
BEGIN
  IF actor IS NULL THEN
    RAISE EXCEPTION 'Missing verified identity' USING ERRCODE = '28000';
  END IF;
  SELECT * INTO u FROM edu.users x WHERE x.id = actor;
  RETURN jsonb_build_object('kind', 'self_export', 'generatedAt', clock_timestamp(),
    'profile', jsonb_build_object('userId', u.id, 'email', u.email,
                                  'displayName', u.display_name, 'createdAt', u.created_at),
    'memberships', (
      SELECT coalesce(jsonb_agg(jsonb_build_object(
          'workspaceId', w.id, 'workspaceName', w.name, 'role', m.role, 'status', m.status,
          'createdAt', m.created_at) ORDER BY m.created_at), '[]'::jsonb)
      FROM edu.workspace_members m JOIN edu.workspaces w ON w.id = m.workspace_id
      WHERE m.user_id = actor),
    'students', (
      SELECT coalesce(jsonb_agg(edu.privacy_student_payload(s.id) ORDER BY s.created_at),
                      '[]'::jsonb)
      FROM edu.students s WHERE s.user_id = actor));
END $$;
"""

# 0015 body of edu.student_start_attempt plus the consent gate (EV017) after enrollment.
START_ATTEMPT_SQL = """
CREATE FUNCTION edu.student_start_attempt(p_assignment_id uuid, p_idempotency_key text,
    p_request_hash text, p_consent_age integer)
  RETURNS TABLE(out_attempt_id uuid, out_created boolean, out_status text,
                out_attempt_no integer, out_started_at timestamptz,
                out_deadline_at timestamptz, out_server_now timestamptz)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
DECLARE
  actor uuid := edu.actor_id();
  asg edu.assignments%ROWTYPE;
  stu uuid;
  stu_consent text;
  stu_birth_year integer;
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
     OR p_request_hash IS NULL OR length(p_request_hash) NOT BETWEEN 1 AND 128
     OR p_consent_age IS NULL OR p_consent_age NOT BETWEEN 12 AND 18 THEN
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
  -- PILOT-05 consent gate: under-age (or unknown age) students need a recorded consent.
  SELECT s.consent_status, s.birth_year INTO stu_consent, stu_birth_year
    FROM edu.students s WHERE s.id = stu;
  IF edu.privacy_consent_required(stu_consent, stu_birth_year, p_consent_age) THEN
    RAISE EXCEPTION 'Guardian consent required' USING ERRCODE = 'EV017';
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

-- The 0015 signature stays callable (default consent age 16) so nothing else breaks.
CREATE OR REPLACE FUNCTION edu.student_start_attempt(p_assignment_id uuid,
    p_idempotency_key text, p_request_hash text)
  RETURNS TABLE(out_attempt_id uuid, out_created boolean, out_status text,
                out_attempt_no integer, out_started_at timestamptz,
                out_deadline_at timestamptz, out_server_now timestamptz)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
BEGIN
  RETURN QUERY SELECT * FROM edu.student_start_attempt(p_assignment_id, p_idempotency_key,
    p_request_hash, 16);
END $$;
"""

INTERNAL_FUNCTIONS = (
    "edu.privacy_min_age(integer)",
    "edu.privacy_consent_required(text, integer, integer)",
    "edu.privacy_staff_role(uuid)",
    "edu.privacy_student_payload(uuid)",
    "edu.privacy_erase_student_row(uuid)",
)

PUBLIC_FUNCTIONS = (
    "edu.student_set_birth_year(integer, integer)",
    "edu.student_consent_status(integer)",
    "edu.consent_link_info(bytea)",
    "edu.guardian_consent_by_link(bytea, text, bytea, text)",
    "edu.erase_student(uuid)",
    "edu.erase_self()",
    "edu.student_export(uuid)",
    "edu.self_export()",
    "edu.student_start_attempt(uuid, text, text, integer)",
)


def upgrade():
    op.execute(STUDENTS_SQL)
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
    op.execute(FUNCTIONS_SQL)
    op.execute(START_ATTEMPT_SQL)
    owners = "\n".join(
        f"ALTER FUNCTION {signature} OWNER TO eduvia_identity_owner;"
        for signature in (*INTERNAL_FUNCTIONS, *PUBLIC_FUNCTIONS)
    )
    op.execute(f"""
    {owners}
    REVOKE ALL ON FUNCTION {", ".join((*INTERNAL_FUNCTIONS, *PUBLIC_FUNCTIONS))} FROM PUBLIC;
    REVOKE CREATE ON SCHEMA edu FROM eduvia_identity_owner;
    """)
    op.execute(f"""
    DO $$ BEGIN
      IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduvia_runtime') THEN
        -- Default privileges grant more; replace them with the exact lean set (no DELETE).
        REVOKE ALL ON edu.student_consents, edu.consent_links, edu.privacy_requests
          FROM eduvia_runtime;
        GRANT SELECT, INSERT, UPDATE ON edu.student_consents, edu.consent_links,
          edu.privacy_requests TO eduvia_runtime;
        GRANT EXECUTE ON FUNCTION {", ".join(PUBLIC_FUNCTIONS)} TO eduvia_runtime;
      END IF;
    END $$;
    """)


def downgrade():
    raise RuntimeError("Privacy migration is forward-only; restore a reviewed backup instead")
