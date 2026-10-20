-- New disposable database only. Credentials are read by psql from environment,
-- never interpolated into files or process arguments. Exclude setup from telemetry.
SET pg_stat_statements.track = 'none';
\getenv app_password GROT_DB_APP_PASSWORD
\getenv monitor_password GROT_DB_MONITOR_PASSWORD
CREATE ROLE grot_orders LOGIN PASSWORD :'app_password';
CREATE ROLE "db-o11y" LOGIN PASSWORD :'monitor_password';
REVOKE ALL ON DATABASE orders FROM PUBLIC;
GRANT CONNECT ON DATABASE orders TO grot_orders, "db-o11y";
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO grot_orders;
GRANT USAGE ON SCHEMA public TO "db-o11y";
GRANT pg_monitor TO "db-o11y";
ALTER ROLE "db-o11y" SET pg_stat_statements.track = 'none';
ALTER DEFAULT PRIVILEGES FOR ROLE grot_orders IN SCHEMA public GRANT SELECT ON TABLES TO "db-o11y";
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
