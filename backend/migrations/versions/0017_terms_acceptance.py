"""Decision 0009: user agreement + privacy notice accepted at registration; guardian consent
becomes optional (``PRIVACY_CONSENT_MODE``, default ``signup``).

* ``edu.user_agreements`` records, per user, which version of each document was accepted, when
  and how (``signup`` | ``reaccept``) plus an optional sha256 of the browser user agent (never
  the IP address). It is per user, not per workspace: FORCE RLS with ``user_id =
  edu.actor_id()``; the runtime role gets SELECT/INSERT only (append-only evidence).
* ``edu.record_agreements`` (SECURITY DEFINER) inserts both rows for the verified actor,
  idempotently (``ON CONFLICT DO NOTHING``), and returns how many rows were new.
  ``edu.current_agreements`` returns the actor's latest accepted version per document.
* Consent mode: the API passes the sentinel consent age ``0`` in ``signup`` mode. The 0016
  functions are replaced so that ``p_consent_age <= 0`` means "consent not required":
  ``edu.student_start_attempt`` never raises EV017, ``edu.student_consent_status`` and
  ``edu.student_set_birth_year`` report ``not_required`` (a self-declared birth year is still
  stored; the stored consent status is left untouched so ``guardian`` mode can be re-enabled
  without a migration). Ages 12..18 behave exactly as in 0016.
* Forward-only, like 0016.
"""

from alembic import op

revision = "0017_terms_acceptance"
down_revision = "0016_privacy_consent"
branch_labels = None
depends_on = None

# Lower-bound age from a birth year (the birthday may not have passed yet this year).
LOCAL_YEAR = "extract(year FROM clock_timestamp() AT TIME ZONE 'Asia/Ho_Chi_Minh')::integer"

SELF_PREDICATE = "user_id = edu.actor_id()"

TABLE_SQL = """
CREATE TABLE edu.user_agreements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES edu.users(id),
  document text NOT NULL CHECK (document IN ('user_agreement','privacy_notice')),
  version text NOT NULL CHECK (version ~ '^[A-Za-z0-9._-]{1,32}$'),
  accepted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  method text NOT NULL CHECK (method IN ('signup','reaccept')),
  client_hash bytea CHECK (client_hash IS NULL OR octet_length(client_hash) = 32),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_user_agreements_user_document_version UNIQUE (user_id, document, version)
);
CREATE INDEX ix_user_agreements_user ON edu.user_agreements(user_id, document, accepted_at);
"""

RLS_SQL = f"""
ALTER TABLE edu.user_agreements ENABLE ROW LEVEL SECURITY;
ALTER TABLE edu.user_agreements FORCE ROW LEVEL SECURITY;
CREATE POLICY user_agreements_self_select ON edu.user_agreements FOR SELECT
  USING ({SELF_PREDICATE});
CREATE POLICY user_agreements_self_insert ON edu.user_agreements FOR INSERT
  WITH CHECK ({SELF_PREDICATE});
"""

AGREEMENT_FUNCTIONS_SQL = """
-- Both documents for the verified actor; replaying the same versions inserts nothing.
CREATE FUNCTION edu.record_agreements(p_user_agreement_version text, p_privacy_version text,
    p_method text, p_client_hash bytea) RETURNS integer
  LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
DECLARE
  actor uuid := edu.actor_id();
  inserted integer;
BEGIN
  IF actor IS NULL THEN
    RAISE EXCEPTION 'Missing verified identity' USING ERRCODE = '28000';
  END IF;
  IF p_user_agreement_version IS NULL
     OR p_user_agreement_version !~ '^[A-Za-z0-9._-]{1,32}$'
     OR p_privacy_version IS NULL OR p_privacy_version !~ '^[A-Za-z0-9._-]{1,32}$'
     OR p_method IS NULL OR p_method NOT IN ('signup','reaccept')
     OR (p_client_hash IS NOT NULL AND octet_length(p_client_hash) <> 32) THEN
    RAISE EXCEPTION 'Invalid agreement' USING ERRCODE = '22023';
  END IF;
  INSERT INTO edu.user_agreements(user_id, document, version, method, client_hash)
    VALUES (actor, 'user_agreement', p_user_agreement_version, p_method, p_client_hash),
           (actor, 'privacy_notice', p_privacy_version, p_method, p_client_hash)
    ON CONFLICT (user_id, document, version) DO NOTHING;
  GET DIAGNOSTICS inserted = ROW_COUNT;
  RETURN inserted;
END $$;

-- The actor's latest accepted version per document (empty without a verified actor).
CREATE FUNCTION edu.current_agreements()
  RETURNS TABLE(out_document text, out_version text, out_accepted_at timestamptz,
                out_method text)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
    SELECT DISTINCT ON (a.document) a.document, a.version, a.accepted_at, a.method
    FROM edu.user_agreements a
    WHERE a.user_id = edu.actor_id()
    ORDER BY a.document, a.accepted_at DESC, a.id DESC
  $$;
"""

# 0016 bodies with one change each: a consent age <= 0 (signup mode) means "not required".
CONSENT_MODE_SQL = f"""
CREATE OR REPLACE FUNCTION edu.privacy_consent_required(p_status text, p_birth_year integer,
    p_consent_age integer) RETURNS boolean
  LANGUAGE sql STABLE SET search_path=pg_catalog,edu AS $$
    SELECT p_consent_age > 0
      AND p_status IN ('unknown','pending','revoked')
      AND (p_birth_year IS NULL OR edu.privacy_min_age(p_birth_year) < p_consent_age)
  $$;

CREATE OR REPLACE FUNCTION edu.student_set_birth_year(p_year integer, p_consent_age integer)
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
  IF p_consent_age IS NULL OR (p_consent_age > 0 AND p_consent_age NOT BETWEEN 12 AND 18)
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
    IF p_consent_age <= 0 THEN
      -- Signup mode: keep the stored status so guardian mode can be re-enabled later.
      UPDATE edu.students s SET birth_year = p_year, updated_at = clock_timestamp()
        WHERE s.id = r.id;
      out_workspace_id := r.workspace_id;
      out_student_id := r.id;
      out_consent_status := 'not_required';
      out_consent_required := false;
      RETURN NEXT;
      CONTINUE;
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

CREATE OR REPLACE FUNCTION edu.student_consent_status(p_consent_age integer)
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
  IF p_consent_age IS NULL OR (p_consent_age > 0 AND p_consent_age NOT BETWEEN 12 AND 18) THEN
    RAISE EXCEPTION 'Invalid consent age' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY SELECT s.workspace_id, w.name::text, s.id,
    (SELECT c.name::text FROM edu.enrollments e
      JOIN edu.classes c ON c.workspace_id = e.workspace_id AND c.id = e.class_id
      WHERE e.workspace_id = s.workspace_id AND e.student_id = s.id AND e.status = 'active'
      ORDER BY e.joined_at DESC NULLS LAST, c.id LIMIT 1),
    s.birth_year::integer,
    CASE WHEN p_consent_age <= 0 THEN 'not_required' ELSE s.consent_status END,
    edu.privacy_consent_required(s.consent_status, s.birth_year, p_consent_age)
  FROM edu.students s JOIN edu.workspaces w ON w.id = s.workspace_id AND w.is_active
  WHERE s.user_id = actor AND s.status = 'active' AND s.erased_at IS NULL
  ORDER BY w.name, s.id;
END $$;
"""

# 0016 body of edu.student_start_attempt; only the consent-age check and the gate change.
START_ATTEMPT_SQL = """
CREATE OR REPLACE FUNCTION edu.student_start_attempt(p_assignment_id uuid,
    p_idempotency_key text, p_request_hash text, p_consent_age integer)
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
     OR p_consent_age IS NULL
     OR (p_consent_age > 0 AND p_consent_age NOT BETWEEN 12 AND 18) THEN
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
  -- 0017: a consent age <= 0 is the signup-mode sentinel (decision 0009): never required.
  SELECT s.consent_status, s.birth_year INTO stu_consent, stu_birth_year
    FROM edu.students s WHERE s.id = stu;
  IF p_consent_age > 0
     AND edu.privacy_consent_required(stu_consent, stu_birth_year, p_consent_age) THEN
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
"""

AGREEMENT_FUNCTIONS = (
    "edu.record_agreements(text, text, text, bytea)",
    "edu.current_agreements()",
)


def upgrade():
    op.execute(TABLE_SQL)
    op.execute(RLS_SQL)
    op.execute("""
    GRANT CREATE ON SCHEMA edu TO eduvia_identity_owner;
    GRANT SELECT, INSERT ON edu.user_agreements TO eduvia_identity_owner;
    """)
    op.execute(AGREEMENT_FUNCTIONS_SQL)
    # CREATE OR REPLACE keeps the 0016 owner (eduvia_identity_owner) and grants.
    op.execute(CONSENT_MODE_SQL)
    op.execute(START_ATTEMPT_SQL)
    owners = "\n".join(
        f"ALTER FUNCTION {signature} OWNER TO eduvia_identity_owner;"
        for signature in AGREEMENT_FUNCTIONS
    )
    op.execute(f"""
    {owners}
    REVOKE ALL ON FUNCTION {", ".join(AGREEMENT_FUNCTIONS)} FROM PUBLIC;
    REVOKE CREATE ON SCHEMA edu FROM eduvia_identity_owner;
    """)
    op.execute(f"""
    DO $$ BEGIN
      IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduvia_runtime') THEN
        -- Default privileges grant more; acceptance evidence is append-only for the runtime.
        REVOKE ALL ON edu.user_agreements FROM eduvia_runtime;
        GRANT SELECT, INSERT ON edu.user_agreements TO eduvia_runtime;
        GRANT EXECUTE ON FUNCTION {", ".join(AGREEMENT_FUNCTIONS)} TO eduvia_runtime;
      END IF;
    END $$;
    """)


def downgrade():
    raise RuntimeError("Terms acceptance migration is forward-only; restore a reviewed backup")
