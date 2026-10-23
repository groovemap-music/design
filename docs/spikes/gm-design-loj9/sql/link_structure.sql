-- SPDX-License-Identifier: MIT
-- How the catalogs' own links shape a work -> edition ladder (spike gm-design-loj9).
--
-- Read-only, through scripts/run_sql.sh. It reads only the provider-keyed tables
-- (`public.releases`, `public.masters`, `musicbrainz.releases`, `musicbrainz.release_groups`),
-- so it runs on any catalog that loaded both dumps, with or without native identity. It is
-- not identity history: it has no transaction time. It measures the ceiling the history can
-- reach, because every cross-catalog identity event (a link at ingest or a re-attachment)
-- starts from a MusicBrainz row that names a Discogs counterpart.
--
-- A Discogs master id is usable when it is non-empty and not the "no master" sentinel `0`,
-- the rule database-schema's `_usable_id` applies to `derived_from`.
WITH
linked AS (
    SELECT m.discogs_release_id::text AS release_id, m.release_group_mbid
    FROM musicbrainz.releases AS m
    WHERE m.discogs_release_id IS NOT NULL
),
joined AS (
    SELECT l.release_id,
           d.data_id IS NOT NULL AS release_loaded,
           CASE WHEN NULLIF(btrim(d.data ->> 'master_id'), '') IS NOT NULL AND btrim(d.data ->> 'master_id') <> '0'
                THEN btrim(d.data ->> 'master_id') END AS release_master,
           rg.discogs_master_id::text AS group_master
    FROM linked AS l
    LEFT JOIN public.releases AS d ON d.data_id = l.release_id
    LEFT JOIN musicbrainz.release_groups AS rg ON rg.mbid = l.release_group_mbid
),
classified AS (
    SELECT j.*,
           j.release_master IS NOT NULL
               AND EXISTS (SELECT 1 FROM public.masters AS dm WHERE dm.data_id = j.release_master) AS release_master_loaded
    FROM joined AS j
),
per_work AS (
    SELECT release_master, count(DISTINCT release_id) AS editions
    FROM classified
    WHERE release_loaded AND release_master_loaded
    GROUP BY release_master
),
per_release AS (
    SELECT release_id, count(*) AS links
    FROM classified
    WHERE release_loaded
    GROUP BY release_id
),
groups AS (
    SELECT count(*) AS rows,
           count(*) FILTER (WHERE rg.discogs_master_id IS NOT NULL) AS linked,
           count(*) FILTER (WHERE rg.discogs_master_id IS NOT NULL AND dm.data_id IS NULL) AS linked_master_missing
    FROM musicbrainz.release_groups AS rg
    LEFT JOIN public.masters AS dm ON dm.data_id = rg.discogs_master_id::text
)
SELECT json_build_object(
    'musicbrainz_releases', (SELECT count(*) FROM musicbrainz.releases),
    'discogs_releases', (SELECT count(*) FROM public.releases),
    'discogs_masters', (SELECT count(*) FROM public.masters),
    'linked', (SELECT count(*) FROM classified),
    'linked_release_loaded', (SELECT count(*) FROM classified WHERE release_loaded),
    'linked_release_missing', (SELECT count(*) FROM classified WHERE NOT release_loaded),
    'discogs_releases_linked', (SELECT count(*) FROM per_release),
    'discogs_releases_linked_from_2plus', (SELECT count(*) FROM per_release WHERE links >= 2),
    'work_relation', (SELECT json_build_object(
        'same_master', count(*) FILTER (WHERE release_master IS NOT NULL AND group_master = release_master),
        'different_master', count(*) FILTER (WHERE release_master IS NOT NULL AND group_master IS NOT NULL AND group_master <> release_master),
        'group_unlinked_release_has_master', count(*) FILTER (WHERE release_master IS NOT NULL AND group_master IS NULL),
        'release_masterless_group_linked', count(*) FILTER (WHERE release_master IS NULL AND group_master IS NOT NULL),
        'both_masterless', count(*) FILTER (WHERE release_master IS NULL AND group_master IS NULL))
        FROM classified WHERE release_loaded),
    'two_work_parents', (SELECT count(*) FROM classified
        WHERE release_loaded AND release_master_loaded AND group_master IS DISTINCT FROM release_master),
    'works_with_linked_editions', (SELECT count(*) FROM per_work),
    'works_with_2plus_linked_editions', (SELECT count(*) FROM per_work WHERE editions >= 2),
    'linked_editions_per_work', (SELECT json_build_object(
        'p50', percentile_disc(0.5) WITHIN GROUP (ORDER BY editions),
        'p90', percentile_disc(0.9) WITHIN GROUP (ORDER BY editions),
        'p99', percentile_disc(0.99) WITHIN GROUP (ORDER BY editions),
        'max', max(editions)) FROM per_work),
    'release_groups', (SELECT json_build_object(
        'rows', rows, 'linked', linked, 'linked_master_missing', linked_master_missing) FROM groups)
);
