"""Classes, class teachers, students, enrollments and class invitations (CLASS-01..03).

Every table is tenant-scoped (non-null workspace_id, composite FKs) with ENABLE + FORCE RLS.
Invitation tokens are stored only as sha256 digests; acceptance runs through the narrow
SECURITY DEFINER function edu.accept_class_invitation because the accepting student is not a
member of the teacher's workspace and RLS would otherwise hide the invitation row.
"""

from alembic import op

revision = "0009_classes"
down_revision = "0008_remove_auth0_transfer"
branch_labels = None
depends_on = None

TABLES = ("classes", "class_teachers", "students", "class_invitations", "enrollments")
TENANT_PREDICATE = (
    "workspace_id::text = current_setting('edu.current_workspace_id', true) "
    "AND edu.can_read_workspace(workspace_id)"
)


def tenant_rls(table: str) -> str:
    p = TENANT_PREDICATE
    return f"""
    ALTER TABLE edu.{table} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE edu.{table} FORCE ROW LEVEL SECURITY;
    CREATE POLICY {table}_tenant_select ON edu.{table} FOR SELECT USING ({p});
    CREATE POLICY {table}_tenant_insert ON edu.{table} FOR INSERT WITH CHECK ({p});
    CREATE POLICY {table}_tenant_update ON edu.{table} FOR UPDATE USING ({p}) WITH CHECK ({p});
    CREATE POLICY {table}_tenant_delete ON edu.{table} FOR DELETE USING ({p});
    """


TABLES_SQL = """
CREATE TABLE edu.classes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
  name varchar(200) NOT NULL,
  grade_level text,
  subject text,
  academic_year text,
  status varchar(20) NOT NULL DEFAULT 'active',
  created_by_user_id uuid NOT NULL REFERENCES edu.users(id),
  archived_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_classes_workspace_id_id UNIQUE (workspace_id, id),
  CONSTRAINT ck_classes_status CHECK (status IN ('active','archived')),
  CONSTRAINT ck_classes_archived_at CHECK ((status = 'archived') = (archived_at IS NOT NULL)),
  CONSTRAINT ck_classes_name CHECK (length(btrim(name)) > 0)
);
CREATE INDEX ix_classes_workspace_id_status ON edu.classes(workspace_id, status);

CREATE TABLE edu.class_teachers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
  class_id uuid NOT NULL,
  user_id uuid NOT NULL REFERENCES edu.users(id),
  role varchar(20) NOT NULL DEFAULT 'co_teacher',
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT fk_class_teachers_workspace_id_class_id_classes FOREIGN KEY (workspace_id, class_id)
    REFERENCES edu.classes(workspace_id, id) ON DELETE CASCADE,
  CONSTRAINT uq_class_teachers_class_id_user_id UNIQUE (class_id, user_id),
  CONSTRAINT ck_class_teachers_role CHECK (role IN ('owner','co_teacher'))
);
CREATE UNIQUE INDEX uq_class_teachers_single_owner ON edu.class_teachers(class_id)
  WHERE role = 'owner';
CREATE INDEX ix_class_teachers_workspace_id_user_id ON edu.class_teachers(workspace_id, user_id);

CREATE TABLE edu.students (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
  user_id uuid REFERENCES edu.users(id),
  display_name varchar(255) NOT NULL,
  external_code text,
  status varchar(20) NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_students_workspace_id_id UNIQUE (workspace_id, id),
  CONSTRAINT ck_students_status CHECK (status IN ('active','inactive'))
);
-- Students are identified by account or explicit external code, never merged by name.
CREATE UNIQUE INDEX uq_students_workspace_id_user_id ON edu.students(workspace_id, user_id)
  WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX uq_students_workspace_id_external_code
  ON edu.students(workspace_id, external_code) WHERE external_code IS NOT NULL;
CREATE INDEX ix_students_workspace_id_status ON edu.students(workspace_id, status);

CREATE TABLE edu.class_invitations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
  class_id uuid NOT NULL,
  token_hash bytea NOT NULL,
  expires_at timestamptz NOT NULL,
  max_uses integer NOT NULL DEFAULT 1,
  use_count integer NOT NULL DEFAULT 0,
  created_by_user_id uuid NOT NULL REFERENCES edu.users(id),
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_class_invitations_token_hash UNIQUE (token_hash),
  CONSTRAINT uq_class_invitations_workspace_id_id UNIQUE (workspace_id, id),
  CONSTRAINT fk_class_invitations_workspace_id_class_id_classes
    FOREIGN KEY (workspace_id, class_id) REFERENCES edu.classes(workspace_id, id),
  CONSTRAINT ck_class_invitations_token_hash CHECK (octet_length(token_hash) = 32),
  CONSTRAINT ck_class_invitations_max_uses CHECK (max_uses BETWEEN 1 AND 500),
  CONSTRAINT ck_class_invitations_use_count CHECK (use_count >= 0 AND use_count <= max_uses),
  CONSTRAINT ck_class_invitations_expiry CHECK (
    expires_at > created_at AND expires_at <= created_at + interval '30 days 1 hour')
);
CREATE INDEX ix_class_invitations_class_id ON edu.class_invitations(class_id);

CREATE TABLE edu.enrollments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
  class_id uuid NOT NULL,
  student_id uuid NOT NULL,
  invitation_id uuid,
  status varchar(20) NOT NULL DEFAULT 'invited',
  joined_at timestamptz,
  withdrawn_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_enrollments_workspace_id_id UNIQUE (workspace_id, id),
  CONSTRAINT uq_enrollments_class_id_student_id UNIQUE (class_id, student_id),
  CONSTRAINT fk_enrollments_workspace_id_class_id_classes
    FOREIGN KEY (workspace_id, class_id) REFERENCES edu.classes(workspace_id, id),
  CONSTRAINT fk_enrollments_workspace_id_student_id_students
    FOREIGN KEY (workspace_id, student_id) REFERENCES edu.students(workspace_id, id),
  CONSTRAINT fk_enrollments_workspace_id_invitation_id_class_invitations
    FOREIGN KEY (workspace_id, invitation_id) REFERENCES edu.class_invitations(workspace_id, id),
  CONSTRAINT ck_enrollments_status CHECK (status IN ('invited','active','withdrawn')),
  CONSTRAINT ck_enrollments_withdrawn_at
    CHECK ((status = 'withdrawn') = (withdrawn_at IS NOT NULL)),
  CONSTRAINT ck_enrollments_joined_at CHECK (status <> 'active' OR joined_at IS NOT NULL)
);
CREATE INDEX ix_enrollments_workspace_id_status ON edu.enrollments(workspace_id, status);
CREATE INDEX ix_enrollments_class_id_status ON edu.enrollments(class_id, status);
CREATE INDEX ix_enrollments_student_id ON edu.enrollments(student_id);
"""

FUNCTIONS_SQL = """
-- Narrow privileged access for the definer functions below (NOLOGIN owner role, as in 0004).
GRANT SELECT ON edu.classes TO eduvia_identity_owner;
GRANT SELECT, UPDATE ON edu.class_invitations TO eduvia_identity_owner;
GRANT SELECT, INSERT, UPDATE ON edu.students, edu.enrollments TO eduvia_identity_owner;
CREATE POLICY classes_invitation_function ON edu.classes FOR SELECT TO eduvia_identity_owner
  USING (true);
CREATE POLICY class_invitations_invitation_function ON edu.class_invitations
  TO eduvia_identity_owner USING (true) WITH CHECK (true);
CREATE POLICY students_invitation_function ON edu.students TO eduvia_identity_owner
  USING (true) WITH CHECK (true);
CREATE POLICY enrollments_invitation_function ON edu.enrollments TO eduvia_identity_owner
  USING (true) WITH CHECK (true);
GRANT CREATE ON SCHEMA edu TO eduvia_identity_owner;

-- Role of another active staff member of the CURRENT workspace, visible only to its members.
CREATE FUNCTION edu.workspace_staff_role(p_workspace uuid, p_user uuid) RETURNS text
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
    SELECT m.role FROM edu.workspace_members m JOIN edu.users u ON u.id = m.user_id
    WHERE m.workspace_id = p_workspace AND m.user_id = p_user AND m.status = 'active'
      AND u.is_active AND m.role IN ('owner','admin','teacher')
      AND p_workspace::text = current_setting('edu.current_workspace_id', true)
      AND edu.can_read_workspace(p_workspace)
  $$;
ALTER FUNCTION edu.workspace_staff_role(uuid, uuid) OWNER TO eduvia_identity_owner;

-- Single-use/atomic acceptance. Errors: P0002 unknown token, EV001 revoked/expired/used up or
-- class unavailable, EV002 withdrawn by this invitation or inactive student, 28000 no identity.
CREATE FUNCTION edu.accept_class_invitation(p_token_hash bytea)
  RETURNS TABLE(out_enrollment_id uuid, out_class_id uuid, out_class_name text,
                out_workspace_id uuid)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
DECLARE
  actor uuid := edu.actor_id();
  inv edu.class_invitations%ROWTYPE;
  cls edu.classes%ROWTYPE;
  stu_id uuid;
  stu_status text;
  enr_id uuid;
  enr_status text;
  enr_invitation uuid;
  actor_name text;
BEGIN
  IF actor IS NULL THEN
    RAISE EXCEPTION 'Missing verified identity' USING ERRCODE = '28000';
  END IF;
  SELECT * INTO inv FROM edu.class_invitations i WHERE i.token_hash = p_token_hash FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Invitation not found' USING ERRCODE = 'P0002';
  END IF;
  IF inv.revoked_at IS NOT NULL OR inv.expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'Invitation unavailable' USING ERRCODE = 'EV001';
  END IF;
  SELECT * INTO cls FROM edu.classes c WHERE c.workspace_id = inv.workspace_id
    AND c.id = inv.class_id;
  IF cls.status <> 'active' OR NOT EXISTS (SELECT 1 FROM edu.workspaces w
      WHERE w.id = inv.workspace_id AND w.is_active) THEN
    RAISE EXCEPTION 'Class unavailable' USING ERRCODE = 'EV001';
  END IF;
  SELECT s.id, s.status INTO stu_id, stu_status FROM edu.students s
    WHERE s.workspace_id = inv.workspace_id AND s.user_id = actor FOR UPDATE;
  IF stu_id IS NOT NULL THEN
    IF stu_status <> 'active' THEN
      RAISE EXCEPTION 'Student inactive' USING ERRCODE = 'EV002';
    END IF;
    SELECT e.id, e.status, e.invitation_id INTO enr_id, enr_status, enr_invitation
      FROM edu.enrollments e WHERE e.class_id = inv.class_id AND e.student_id = stu_id
      FOR UPDATE;
    IF enr_status = 'active' THEN
      -- Idempotent repeat by an enrolled student; does not consume a use.
      RETURN QUERY SELECT enr_id, cls.id, cls.name::text, cls.workspace_id;
      RETURN;
    END IF;
    IF enr_status = 'withdrawn' AND enr_invitation = inv.id THEN
      RAISE EXCEPTION 'Enrollment withdrawn' USING ERRCODE = 'EV002';
    END IF;
  END IF;
  IF inv.use_count >= inv.max_uses THEN
    RAISE EXCEPTION 'Invitation unavailable' USING ERRCODE = 'EV001';
  END IF;
  IF stu_id IS NULL THEN
    SELECT u.display_name INTO actor_name FROM edu.users u WHERE u.id = actor;
    INSERT INTO edu.students(workspace_id, user_id, display_name)
      VALUES (inv.workspace_id, actor,
              left(coalesce(nullif(btrim(actor_name), ''), 'Học sinh'), 255))
      ON CONFLICT (workspace_id, user_id) WHERE user_id IS NOT NULL DO NOTHING
      RETURNING id INTO stu_id;
    IF stu_id IS NULL THEN
      SELECT s.id INTO stu_id FROM edu.students s
        WHERE s.workspace_id = inv.workspace_id AND s.user_id = actor;
    END IF;
  END IF;
  INSERT INTO edu.enrollments(workspace_id, class_id, student_id, invitation_id, status,
                              joined_at)
    VALUES (inv.workspace_id, inv.class_id, stu_id, inv.id, 'active', clock_timestamp())
    ON CONFLICT (class_id, student_id) DO UPDATE SET status = 'active',
      joined_at = clock_timestamp(), withdrawn_at = NULL,
      invitation_id = excluded.invitation_id, updated_at = clock_timestamp()
    RETURNING id INTO enr_id;
  UPDATE edu.class_invitations i SET use_count = i.use_count + 1,
    updated_at = clock_timestamp() WHERE i.id = inv.id;
  RETURN QUERY SELECT enr_id, cls.id, cls.name::text, cls.workspace_id;
END $$;
ALTER FUNCTION edu.accept_class_invitation(bytea) OWNER TO eduvia_identity_owner;
REVOKE ALL ON FUNCTION edu.workspace_staff_role(uuid, uuid), edu.accept_class_invitation(bytea)
  FROM PUBLIC;
REVOKE CREATE ON SCHEMA edu FROM eduvia_identity_owner;
"""

RUNTIME_GRANTS_SQL = """
DO $$ BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduvia_runtime') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON edu.classes, edu.class_teachers, edu.students,
      edu.class_invitations, edu.enrollments TO eduvia_runtime;
    -- All keys are UUIDs; no sequences exist. Kept for future serial columns in edu.
    GRANT USAGE ON ALL SEQUENCES IN SCHEMA edu TO eduvia_runtime;
    GRANT EXECUTE ON FUNCTION edu.workspace_staff_role(uuid, uuid),
      edu.accept_class_invitation(bytea) TO eduvia_runtime;
  END IF;
END $$;
"""


def upgrade():
    op.execute(TABLES_SQL)
    for table in TABLES:
        op.execute(tenant_rls(table))
    op.execute(FUNCTIONS_SQL)
    op.execute(RUNTIME_GRANTS_SQL)


def downgrade():
    op.execute("""
    DROP FUNCTION IF EXISTS edu.accept_class_invitation(bytea);
    DROP FUNCTION IF EXISTS edu.workspace_staff_role(uuid, uuid);
    DROP TABLE IF EXISTS edu.enrollments;
    DROP TABLE IF EXISTS edu.class_invitations;
    DROP TABLE IF EXISTS edu.students;
    DROP TABLE IF EXISTS edu.class_teachers;
    DROP TABLE IF EXISTS edu.classes;
    """)
