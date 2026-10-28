-- Database roles. The owner runs migrations; the application role is subject to
-- row-level security (no BYPASSRLS) and cannot UPDATE/DELETE audit events.
-- Passwords here are local-development defaults; production injects secrets.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ngsirs_owner') THEN
    CREATE ROLE ngsirs_owner LOGIN PASSWORD 'ngsirs_owner';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ngsirs_app') THEN
    CREATE ROLE ngsirs_app LOGIN PASSWORD 'ngsirs_app' NOBYPASSRLS;
  END IF;
END $$;
