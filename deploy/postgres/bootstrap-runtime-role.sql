-- Run once with the migration/administrative identity, then use psql's
-- \password doctrace_app interactively. Never put passwords in this file.
-- Re-running does not reset credentials. Alembic applies table grants.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'doctrace_app') THEN
        CREATE ROLE doctrace_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'doctrace_app'
        AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
    ) OR EXISTS (
        SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member
        WHERE r.rolname = 'doctrace_app'
    ) THEN
        RAISE EXCEPTION 'doctrace_app must be an unprivileged, dedicated login without role memberships';
    END IF;
END
$$;
