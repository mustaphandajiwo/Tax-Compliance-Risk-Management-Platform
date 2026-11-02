-- Database roles. The owner runs migrations; the application role is subject to
-- row-level security (no BYPASSRLS) and cannot UPDATE/DELETE audit events.
-- Passwords here are local-development defaults; production injects secrets.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'taxrisk_owner') THEN
    CREATE ROLE taxrisk_owner LOGIN PASSWORD 'taxrisk_owner';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'taxrisk_app') THEN
    CREATE ROLE taxrisk_app LOGIN PASSWORD 'taxrisk_app' NOBYPASSRLS;
  END IF;
END $$;
