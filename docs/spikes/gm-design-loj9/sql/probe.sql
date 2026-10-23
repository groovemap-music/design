-- SPDX-License-Identifier: MIT
-- Does this database hold GrooveMap identity history? (spike gm-design-loj9)
--
-- Read-only, through scripts/run_sql.sh. Reports which of the tables
-- sql/identity_history.sql reads exist, and how many audit rows and identity audit rows
-- there are. A count is taken only when its table exists, so the probe runs on any
-- PostgreSQL database, including the predecessor catalog that has none of them.
SELECT json_build_object(
    'tables', json_build_object(
        'catalog_items', to_regclass('public.catalog_items') IS NOT NULL,
        'provider_aliases', to_regclass('public.provider_aliases') IS NOT NULL,
        'catalog_item_supersessions', to_regclass('public.catalog_item_supersessions') IS NOT NULL,
        'catalog_item_moves', to_regclass('public.catalog_item_moves') IS NOT NULL,
        'admin_audit_log', to_regclass('public.admin_audit_log') IS NOT NULL,
        'releases', to_regclass('public.releases') IS NOT NULL,
        'masters', to_regclass('public.masters') IS NOT NULL,
        'musicbrainz.releases', to_regclass('musicbrainz.releases') IS NOT NULL,
        'musicbrainz.release_groups', to_regclass('musicbrainz.release_groups') IS NOT NULL),
    'admin_audit_log_rows', CASE WHEN to_regclass('public.admin_audit_log') IS NOT NULL THEN
        (xpath('/row/n/text()', query_to_xml('SELECT count(*) AS n FROM public.admin_audit_log', false, true, '')))[1]::text::bigint END,
    'admin_audit_log_identity_rows', CASE WHEN to_regclass('public.admin_audit_log') IS NOT NULL THEN
        (xpath('/row/n/text()', query_to_xml(
            'SELECT count(*) AS n FROM public.admin_audit_log WHERE action LIKE ''identity.%''', false, true, '')))[1]::text::bigint END,
    'server_version_num', current_setting('server_version_num')::int
);
