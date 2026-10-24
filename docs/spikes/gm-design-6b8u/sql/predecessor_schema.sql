-- SPDX-License-Identifier: MIT
-- Read-only schema and content check of the predecessor catalog (spike gm-design-6b8u). It
-- covers the four tables gm-design-loj9's sql/link_structure.sql reads. Pipe it to psql
-- between `BEGIN TRANSACTION READ ONLY; SET LOCAL statement_timeout = '300s';` and `COMMIT;`
-- (the README has the command). The output is schema and aggregates only.
SELECT 'column|' || table_schema || '.' || table_name || '|' || column_name || '|' || data_type || '|' || is_nullable
FROM information_schema.columns
WHERE (table_schema, table_name) IN (('musicbrainz', 'releases'), ('musicbrainz', 'release_groups'), ('public', 'releases'), ('public', 'masters'))
ORDER BY 1;
SELECT 'index|' || schemaname || '.' || tablename || '|' || indexdef
FROM pg_indexes
WHERE (schemaname, tablename) IN (('musicbrainz', 'releases'), ('musicbrainz', 'release_groups'), ('public', 'releases'), ('public', 'masters'))
ORDER BY 1;
-- How a Discogs release's master_id is stored: a 1% block sample.
SELECT 'master_id_type|' || t || '|' || n
FROM (SELECT coalesce(jsonb_typeof(data -> 'master_id'), 'absent') AS t, count(*) AS n
      FROM (SELECT data FROM public.releases TABLESAMPLE SYSTEM (1)) AS s GROUP BY 1) AS g;
-- When each table was last written: which dumps the snapshot holds.
SELECT 'last_written|musicbrainz.releases|' || to_char(max(updated_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD') FROM musicbrainz.releases;
SELECT 'last_written|musicbrainz.release_groups|' || to_char(max(updated_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD') FROM musicbrainz.release_groups;
SELECT 'last_written|public.releases|' || to_char(max(updated_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD') FROM public.releases;
