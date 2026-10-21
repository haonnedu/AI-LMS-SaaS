-- DB-05 runtime-role RLS smoke test.
-- Runs entirely inside one transaction against the live staging database and
-- ends with ROLLBACK, so it leaves no schema change and no rows behind.
-- It mirrors migration 0003 so the policy text is exercised as written.
\set ON_ERROR_STOP on
SET client_min_messages = notice;

BEGIN;

CREATE OR REPLACE FUNCTION edu.is_active_member() RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, edu
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM edu.workspace_members m
        WHERE m.workspace_id::text = current_setting('edu.current_workspace_id', true)
          AND m.user_id::text = current_setting('edu.current_user_id', true)
          AND m.status = 'active'
    )
$$;
REVOKE ALL ON FUNCTION edu.is_active_member() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION edu.is_active_member() TO eduvia_runtime;

ALTER TABLE edu.workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE edu.workspaces FORCE ROW LEVEL SECURITY;
CREATE POLICY workspace_membership_policy ON edu.workspaces
FOR ALL
USING (
    current_setting('edu.current_workspace_id', true) <> ''
    AND id::text = current_setting('edu.current_workspace_id', true)
    AND edu.is_active_member()
)
WITH CHECK (
    current_setting('edu.current_workspace_id', true) <> ''
    AND id::text = current_setting('edu.current_workspace_id', true)
    AND edu.is_active_member()
);

ALTER TABLE edu.workspace_members ENABLE ROW LEVEL SECURITY;
CREATE POLICY workspace_members_policy ON edu.workspace_members
FOR ALL
USING (
    current_setting('edu.current_workspace_id', true) <> ''
    AND workspace_id::text = current_setting('edu.current_workspace_id', true)
    AND edu.is_active_member()
)
WITH CHECK (
    current_setting('edu.current_workspace_id', true) <> ''
    AND workspace_id::text = current_setting('edu.current_workspace_id', true)
    AND edu.is_active_member()
);

-- Fixtures inserted as the defining role (bypasses RLS while it owns the tables).
INSERT INTO edu.users (id, email, provider_sub, display_name) VALUES
    ('11111111-1111-1111-1111-111111111111', 'a@test.invalid', 'sub-a', 'Tenant A'),
    ('22222222-2222-2222-2222-222222222222', 'b@test.invalid', 'sub-b', 'Tenant B');

INSERT INTO edu.workspaces (id, name, slug, workspace_type) VALUES
    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Workspace A', 'ws-a', 'personal'),
    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'Workspace B', 'ws-b', 'school');

INSERT INTO edu.workspace_members (workspace_id, user_id, role, status) VALUES
    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '11111111-1111-1111-1111-111111111111', 'owner', 'active'),
    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', '22222222-2222-2222-2222-222222222222', 'owner', 'active');

-- ---- assertions executed as the restricted runtime role ----
SET ROLE eduvia_runtime;

DO $$
DECLARE n int;
BEGIN
    PERFORM set_config('edu.current_user_id', '11111111-1111-1111-1111-111111111111', true);
    PERFORM set_config('edu.current_workspace_id', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', true);
    SELECT count(*) INTO n FROM edu.workspaces;
    IF n <> 1 THEN RAISE EXCEPTION 'C1 own workspace visible: expected 1 got %', n; END IF;
    RAISE NOTICE 'PASS C1 own workspace visible';
END $$;

DO $$
DECLARE n int;
BEGIN
    PERFORM set_config('edu.current_user_id', '11111111-1111-1111-1111-111111111111', true);
    PERFORM set_config('edu.current_workspace_id', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', true);
    SELECT count(*) INTO n FROM edu.workspaces;
    IF n <> 0 THEN RAISE EXCEPTION 'C2 forged workspace id: expected 0 got %', n; END IF;
    RAISE NOTICE 'PASS C2 forged workspace id denied';
END $$;

DO $$
DECLARE n int;
BEGIN
    PERFORM set_config('edu.current_user_id', '', true);
    PERFORM set_config('edu.current_workspace_id', '', true);
    SELECT count(*) INTO n FROM edu.workspaces;
    IF n <> 0 THEN RAISE EXCEPTION 'C3 missing context: expected 0 got %', n; END IF;
    SELECT count(*) INTO n FROM edu.workspace_members;
    IF n <> 0 THEN RAISE EXCEPTION 'C3 members missing context: expected 0 got %', n; END IF;
    RAISE NOTICE 'PASS C3 missing context denied';
END $$;

DO $$
DECLARE n int;
BEGIN
    PERFORM set_config('edu.current_user_id', '11111111-1111-1111-1111-111111111111', true);
    PERFORM set_config('edu.current_workspace_id', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', true);
    SELECT count(*) INTO n FROM edu.workspace_members;
    IF n <> 1 THEN RAISE EXCEPTION 'C4 members scoped: expected 1 got %', n; END IF;
    SELECT count(*) INTO n FROM edu.workspace_members
        WHERE workspace_id = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
    IF n <> 0 THEN RAISE EXCEPTION 'C4 cross-tenant members leaked %', n; END IF;
    RAISE NOTICE 'PASS C4 members scoped to own workspace';
END $$;

DO $$
DECLARE blocked boolean := false;
BEGIN
    PERFORM set_config('edu.current_user_id', '11111111-1111-1111-1111-111111111111', true);
    PERFORM set_config('edu.current_workspace_id', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', true);
    BEGIN
        INSERT INTO edu.workspaces (name, slug, workspace_type)
        VALUES ('Injected', 'ws-injected', 'personal');
    EXCEPTION WHEN insufficient_privilege THEN
        blocked := true;
    END;
    IF NOT blocked THEN RAISE EXCEPTION 'C5 negative write was allowed'; END IF;
    RAISE NOTICE 'PASS C5 negative write blocked';
END $$;

DO $$
DECLARE blocked boolean := false;
BEGIN
    PERFORM set_config('edu.current_user_id', '11111111-1111-1111-1111-111111111111', true);
    PERFORM set_config('edu.current_workspace_id', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', true);
    BEGIN
        INSERT INTO edu.workspace_members (workspace_id, user_id, role, status)
        VALUES ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                '11111111-1111-1111-1111-111111111111', 'owner', 'active');
    EXCEPTION WHEN insufficient_privilege THEN
        blocked := true;
    END;
    IF NOT blocked THEN RAISE EXCEPTION 'C6 cross-tenant membership write allowed'; END IF;
    RAISE NOTICE 'PASS C6 cross-tenant membership write blocked';
END $$;

RESET ROLE;

-- Revoked member must lose access immediately.
UPDATE edu.workspace_members SET status = 'suspended'
WHERE workspace_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
  AND user_id = '11111111-1111-1111-1111-111111111111';

SET ROLE eduvia_runtime;

DO $$
DECLARE n int;
BEGIN
    PERFORM set_config('edu.current_user_id', '11111111-1111-1111-1111-111111111111', true);
    PERFORM set_config('edu.current_workspace_id', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', true);
    SELECT count(*) INTO n FROM edu.workspaces;
    IF n <> 0 THEN RAISE EXCEPTION 'C7 revoked member still sees % workspace(s)', n; END IF;
    RAISE NOTICE 'PASS C7 revoked member denied';
END $$;

RESET ROLE;

SET ROLE eduvia_runtime;
DO $$
DECLARE n int; seen text;
BEGIN
    PERFORM set_config('edu.current_user_id', '22222222-2222-2222-2222-222222222222', true);
    PERFORM set_config('edu.current_workspace_id', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', true);
    SELECT count(*), string_agg(name, ',') INTO n, seen FROM edu.workspaces;
    IF n <> 1 OR seen <> 'Workspace B' THEN
        RAISE EXCEPTION 'C8 tenant B saw % row(s): %', n, seen;
    END IF;
    RAISE NOTICE 'PASS C8 tenant B isolated from tenant A';
END $$;
RESET ROLE;

ROLLBACK;
\echo 'RLS smoke complete (transaction rolled back; no schema or data change persisted).'
