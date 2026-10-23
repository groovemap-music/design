-- SPDX-License-Identifier: MIT
-- Which collection and wantlist rows carry a time usable as transaction time.
-- Read-only, aggregate-only: run with a read-only role against the production
-- PostgreSQL, e.g.  psql "$GM_READONLY_DSN" -X -A -F $'\t' -f collector_time.sql
-- It returns counts, never a user id or a row.
--
-- Columns, from database-schema src/groovemap_schema/postgres.py and catalog-api
-- api/syncer.py:
--   date_added  the Discogs API's date_added for the item, copied on every sync
--               (the collector's own recorded time, kept by Discogs)
--   created_at  when GrooveMap's sync first wrote the row (GrooveMap's recorded time)
--   updated_at  overwritten with the sync clock on every run: not transaction time
-- A removed item's row is deleted, so its end time survives only in activity.events
-- (collection.item_removed, wantlist.item_removed) and, for the collection, in
-- collection_snapshots.

SELECT 'user_collections' AS source,
       count(*) AS rows,
       count(date_added) AS with_date_added,
       count(*) FILTER (WHERE date_added IS NOT NULL AND date_added <= created_at) AS date_added_not_after_created_at,
       count(*) FILTER (WHERE date_added IS NOT NULL AND date_added > created_at) AS date_added_after_created_at,
       count(owned_copy_id) AS with_owned_copy,
       count(DISTINCT user_id) AS users
FROM user_collections
UNION ALL
SELECT 'user_wantlists', count(*), count(date_added),
       count(*) FILTER (WHERE date_added IS NOT NULL AND date_added <= created_at),
       count(*) FILTER (WHERE date_added IS NOT NULL AND date_added > created_at),
       NULL, count(DISTINCT user_id)
FROM user_wantlists;

-- Owned copies outlive their collection row (collection_row_id is nulled on removal).
SELECT 'owned_copies' AS source,
       count(*) AS rows,
       count(acquired_at) AS with_acquired_at,
       count(*) FILTER (WHERE collection_row_id IS NULL) AS removed_from_collection
FROM owned_copies;

-- Snapshot history: how far back an "as of" replay of the collection can reach.
SELECT 'collection_snapshots' AS source,
       count(*) AS snapshots,
       count(DISTINCT user_id) AS users,
       min(taken_at)::date AS first_snapshot,
       max(taken_at)::date AS last_snapshot
FROM collection_snapshots;

-- Change events: the only record of when an item left a collection or wantlist.
SELECT event_type, count(*) AS events, min(occurred_at)::date AS first_event
FROM activity.events
WHERE event_type IN ('collection.item_added', 'collection.item_removed', 'collection.item_updated',
                     'wantlist.item_added', 'wantlist.item_removed')
GROUP BY event_type
ORDER BY event_type;
