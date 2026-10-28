-- Minimal Supabase Auth contract for disposable Postgres integration tests.
-- RLS is enabled with no policies, matching hosted auth.users. Extra private
-- columns make SELECT * / accidental credential grants meaningful deny tests.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supabase_admin') THEN
        CREATE ROLE supabase_admin NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supabase_auth_admin') THEN
        CREATE ROLE supabase_auth_admin NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'doctrace_migrator') THEN
        CREATE ROLE doctrace_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION BYPASSRLS PASSWORD 'local-migration-only';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role NOLOGIN BYPASSRLS;
    END IF;
END $$;

-- Reset the single role attribute a readiness fault-injection test changes.
ALTER ROLE doctrace_migrator BYPASSRLS;
CREATE SCHEMA auth AUTHORIZATION supabase_admin;
CREATE TABLE auth.users (
    id uuid PRIMARY KEY,
    deleted_at timestamptz,
    email text,
    encrypted_password text,
    raw_user_meta_data jsonb
);
ALTER TABLE auth.users OWNER TO supabase_auth_admin;
ALTER TABLE auth.users ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON SCHEMA auth FROM PUBLIC;
REVOKE ALL ON auth.users FROM PUBLIC;
-- Hosted postgres can read the necessary columns and bypass RLS, but is not
-- an Auth owner and cannot delegate schema USAGE to custom runtime roles.
GRANT USAGE ON SCHEMA auth TO doctrace_migrator, anon, authenticated, service_role;
GRANT SELECT (id, deleted_at) ON auth.users TO doctrace_migrator WITH GRANT OPTION;
