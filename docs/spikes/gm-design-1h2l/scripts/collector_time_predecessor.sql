-- SPDX-License-Identifier: MIT
-- collector_time.sql translated to the predecessor schema, which has user_collections
-- and user_wantlists without gm_item_id or owned_copy_id, and no owned_copies,
-- collection_snapshots, or activity.events. Read-only and aggregate-only:
--   <read-only psql wrapper> < collector_time_predecessor.sql
begin transaction read only;
set local statement_timeout = '60s';
SELECT 'user_collections' AS source, count(*) AS rows, count(date_added) AS with_date_added,
       count(*) FILTER (WHERE date_added IS NOT NULL AND date_added <= created_at) AS date_added_not_after_created_at,
       count(*) FILTER (WHERE date_added IS NOT NULL AND date_added > created_at) AS date_added_after_created_at,
       count(DISTINCT user_id) AS users
FROM user_collections
UNION ALL
SELECT 'user_wantlists', count(*), count(date_added),
       count(*) FILTER (WHERE date_added IS NOT NULL AND date_added <= created_at),
       count(*) FILTER (WHERE date_added IS NOT NULL AND date_added > created_at),
       count(DISTINCT user_id)
FROM user_wantlists;
SELECT count(*) AS syncs, min(started_at)::date AS first_sync, max(started_at)::date AS last_sync FROM sync_history;
commit;
