-- Runs once on first postgres container start (via docker-entrypoint-initdb.d/).
-- Creates the test database alongside the dev database.

SELECT 'CREATE DATABASE exovance_test OWNER postgres'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'exovance_test'
)\gexec
