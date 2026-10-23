-- SPDX-License-Identifier: MIT
-- Identity history available to concept D's ledger (spike gm-design-loj9).
--
-- Run it through scripts/run_sql.sh, which wraps it in a REPEATABLE READ, READ ONLY
-- transaction. It returns one JSON object of counts, months, and days. No native id,
-- external id, user id, admin id, or audit target leaves the database:
-- catalog_item_moves.user_id and row_id, and admin_audit_log.admin_id and target, are never
-- read. scripts/reference.py defines every figure in prose and computes the same object in
-- Python; tests/test_sql_parity.py holds the two equal on the synthetic fixture.
WITH
supersession AS (
    SELECT s.*, item.kind
    FROM catalog_item_supersessions AS s
    JOIN catalog_items AS item ON item.id = s.superseded_id
),
resolved AS (
    SELECT item.id AS item_id, item.kind, COALESCE(open_row.survivor_id, item.id) AS resolved_id
    FROM catalog_items AS item
    LEFT JOIN catalog_item_supersessions AS open_row
           ON open_row.superseded_id = item.id AND open_row.valid_to IS NULL
),
-- An alias opened on an item at the instant a supersession into it opened, or a supersession
-- out of it closed, was moved by that supersession. Closes mirror it.
moved_in AS (
    SELECT survivor_id AS item_id, valid_from AS at FROM catalog_item_supersessions
    UNION
    SELECT superseded_id, valid_to FROM catalog_item_supersessions WHERE valid_to IS NOT NULL
),
moved_out AS (
    SELECT superseded_id AS item_id, valid_from AS at FROM catalog_item_supersessions
    UNION
    SELECT survivor_id, valid_to FROM catalog_item_supersessions WHERE valid_to IS NOT NULL
),
alias AS (
    SELECT a.provider, a.entity_kind, a.source, a.native_id, a.valid_from, a.valid_to,
           moved_in.item_id IS NOT NULL AS opened_by_supersession,
           moved_out.item_id IS NOT NULL AS closed_by_supersession,
           a.valid_from > min(a.valid_from) OVER (PARTITION BY a.native_id) AS opened_after_mint
    FROM provider_aliases AS a
    LEFT JOIN moved_in ON moved_in.item_id = a.native_id AND moved_in.at = a.valid_from
    LEFT JOIN moved_out ON moved_out.item_id = a.native_id AND moved_out.at = a.valid_to
),
item_link AS (
    SELECT alias.native_id,
           min(alias.valid_from) FILTER (WHERE alias.provider = 'discogs') AS discogs_first,
           min(alias.valid_from) FILTER (WHERE alias.provider = 'musicbrainz' AND NOT alias.opened_by_supersession) AS musicbrainz_first
    FROM alias
    GROUP BY alias.native_id
),
audit AS (
    SELECT action, details, created_at
    FROM admin_audit_log
    WHERE action LIKE 'identity.%'
),
outcome AS (
    SELECT kind.key AS kind, field.name AS field, sum(COALESCE((kind.value ->> field.name)::bigint, 0)) AS total
    FROM audit
    CROSS JOIN LATERAL jsonb_each(COALESCE(audit.details -> 'outcomes', '{}'::jsonb)) AS kind
    CROSS JOIN unnest(ARRAY['reattached', 'guarded', 'failed', 'supersessions_opened', 'merged_with_dependents']) AS field(name)
    WHERE audit.action IN ('identity.reattach.apply', 'identity.reattach.auto')
    GROUP BY kind.key, field.name
),
-- The ledger: an edition is a release-kind item as resolved today, and its instants are
-- everything recorded about it or about an item superseded into it.
instant AS (
    SELECT r.resolved_id AS edition_id, a.valid_from AS at
    FROM provider_aliases AS a JOIN resolved AS r ON r.item_id = a.native_id
    WHERE r.kind = 'release'
    UNION
    SELECT r.resolved_id, a.valid_to
    FROM provider_aliases AS a JOIN resolved AS r ON r.item_id = a.native_id
    WHERE r.kind = 'release' AND a.valid_to IS NOT NULL
    UNION
    SELECT r.resolved_id, s.valid_from
    FROM supersession AS s JOIN resolved AS r ON r.item_id IN (s.superseded_id, s.survivor_id)
    WHERE s.kind = 'release'
    UNION
    SELECT r.resolved_id, s.valid_to
    FROM supersession AS s JOIN resolved AS r ON r.item_id IN (s.superseded_id, s.survivor_id)
    WHERE s.kind = 'release' AND s.valid_to IS NOT NULL
    UNION
    SELECT r.resolved_id, m.moved_at
    FROM catalog_item_moves AS m JOIN resolved AS r ON r.item_id IN (m.from_item_id, m.to_item_id)
    WHERE r.kind = 'release'
),
repaired AS (
    SELECT DISTINCT r.resolved_id AS edition_id
    FROM supersession AS s JOIN resolved AS r ON r.item_id IN (s.superseded_id, s.survivor_id)
    WHERE s.kind = 'release'
),
-- An event is any instant after the edition's first (its mint).
event AS (
    SELECT edition_id, at, at > min(at) OVER (PARTITION BY edition_id) AS is_event
    FROM instant
),
edition AS (
    SELECT i.edition_id,
           count(*) AS instants,
           count(DISTINCT to_char(i.at AT TIME ZONE 'UTC', 'YYYY-MM')) FILTER (WHERE i.is_event) AS months,
           bool_or(repaired.edition_id IS NOT NULL) AS repaired
    FROM event AS i
    LEFT JOIN repaired ON repaired.edition_id = i.edition_id
    GROUP BY i.edition_id
),
-- Each catalog's own release row names its work: a Discogs release its master, a
-- MusicBrainz release its release group (which aliases as entity kind `master`).
edition_work AS (
    SELECT edition.resolved_id AS edition_id, work.resolved_id AS work_id
    FROM public.releases AS d
    JOIN provider_aliases AS ea
      ON ea.provider = 'discogs' AND ea.entity_kind = 'release' AND ea.external_id = d.data_id AND ea.valid_to IS NULL
    JOIN resolved AS edition ON edition.item_id = ea.native_id
    JOIN provider_aliases AS wa
      ON wa.provider = 'discogs' AND wa.entity_kind = 'master' AND wa.external_id = btrim(d.data ->> 'master_id') AND wa.valid_to IS NULL
    JOIN resolved AS work ON work.item_id = wa.native_id
    UNION
    SELECT edition.resolved_id, work.resolved_id
    FROM musicbrainz.releases AS m
    JOIN provider_aliases AS ea
      ON ea.provider = 'musicbrainz' AND ea.entity_kind = 'release' AND ea.external_id = m.mbid::text AND ea.valid_to IS NULL
    JOIN resolved AS edition ON edition.item_id = ea.native_id
    JOIN provider_aliases AS wa
      ON wa.provider = 'musicbrainz' AND wa.entity_kind = 'master' AND wa.external_id = m.release_group_mbid::text AND wa.valid_to IS NULL
    JOIN resolved AS work ON work.item_id = wa.native_id
),
known_edition_work AS (
    SELECT ew.edition_id, ew.work_id, e.instants >= 2 AS evented, e.repaired
    FROM edition_work AS ew JOIN edition AS e ON e.edition_id = ew.edition_id
),
work_count AS (
    SELECT e.edition_id, count(kew.work_id) AS works
    FROM edition AS e LEFT JOIN known_edition_work AS kew ON kew.edition_id = e.edition_id
    GROUP BY e.edition_id
),
per_work AS (
    SELECT work_id, count(*) FILTER (WHERE evented) AS evented, count(*) FILTER (WHERE repaired) AS repaired
    FROM known_edition_work
    GROUP BY work_id
),
work_month AS (
    SELECT kew.work_id, count(DISTINCT to_char(i.at AT TIME ZONE 'UTC', 'YYYY-MM')) AS months
    FROM known_edition_work AS kew JOIN event AS i ON i.edition_id = kew.edition_id
    WHERE kew.evented AND i.is_event
    GROUP BY kew.work_id
),
mb_link AS (
    SELECT ma.native_id AS musicbrainz_native_id, da.native_id AS discogs_native_id
    FROM musicbrainz.releases AS m
    LEFT JOIN provider_aliases AS ma
           ON ma.provider = 'musicbrainz' AND ma.entity_kind = 'release' AND ma.external_id = m.mbid::text AND ma.valid_to IS NULL
    LEFT JOIN provider_aliases AS da
           ON da.provider = 'discogs' AND da.entity_kind = 'release' AND da.external_id = m.discogs_release_id::text AND da.valid_to IS NULL
    WHERE m.discogs_release_id IS NOT NULL
)
SELECT json_build_object(
    'provider_aliases', (
        SELECT json_build_object(
            'rows', count(*),
            'current', count(*) FILTER (WHERE valid_to IS NULL),
            'closed', count(*) FILTER (WHERE valid_to IS NOT NULL),
            'first_opened', to_char(min(valid_from) AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
            'last_opened', to_char(max(valid_from) AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
            'first_closed', to_char(min(valid_to) AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
            'last_closed', to_char(max(valid_to) AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
            'opened_days', count(DISTINCT to_char(valid_from AT TIME ZONE 'UTC', 'YYYY-MM-DD')),
            'by_provider_kind', (SELECT COALESCE(json_object_agg(k, n), '{}') FROM (
                SELECT provider || '/' || entity_kind AS k, count(*) AS n FROM provider_aliases GROUP BY 1) AS g),
            'by_source', (SELECT COALESCE(json_object_agg(source, n), '{}') FROM (
                SELECT source, count(*) AS n FROM provider_aliases GROUP BY 1) AS g),
            'opened_per_month', (SELECT COALESCE(json_object_agg(m, n), '{}') FROM (
                SELECT to_char(valid_from AT TIME ZONE 'UTC', 'YYYY-MM') AS m, count(*) AS n FROM provider_aliases GROUP BY 1) AS g),
            'closed_per_month', (SELECT COALESCE(json_object_agg(m, n), '{}') FROM (
                SELECT to_char(valid_to AT TIME ZONE 'UTC', 'YYYY-MM') AS m, count(*) AS n
                FROM provider_aliases WHERE valid_to IS NOT NULL GROUP BY 1) AS g))
        FROM provider_aliases),
    'catalog_item_supersessions', (
        SELECT json_build_object(
            'rows', count(*),
            'open', count(*) FILTER (WHERE valid_to IS NULL),
            'closed', count(*) FILTER (WHERE valid_to IS NOT NULL),
            'with_via', count(*) FILTER (WHERE via_id IS NOT NULL),
            'decision_refs', count(DISTINCT decision_ref),
            'by_cause', (SELECT COALESCE(json_object_agg(cause, n), '{}') FROM (
                SELECT cause, count(*) AS n FROM supersession GROUP BY 1) AS g),
            'by_kind', (SELECT COALESCE(json_object_agg(kind, n), '{}') FROM (
                SELECT kind, count(*) AS n FROM supersession GROUP BY 1) AS g),
            'first_opened', to_char(min(valid_from) AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
            'last_opened', to_char(max(valid_from) AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
            'opened_per_month', (SELECT COALESCE(json_object_agg(m, n), '{}') FROM (
                SELECT to_char(valid_from AT TIME ZONE 'UTC', 'YYYY-MM') AS m, count(*) AS n FROM supersession GROUP BY 1) AS g),
            'closed_per_month', (SELECT COALESCE(json_object_agg(m, n), '{}') FROM (
                SELECT to_char(valid_to AT TIME ZONE 'UTC', 'YYYY-MM') AS m, count(*) AS n
                FROM supersession WHERE valid_to IS NOT NULL GROUP BY 1) AS g))
        FROM supersession),
    'catalog_item_moves', (
        SELECT json_build_object(
            'rows', count(*),
            'by_table', (SELECT COALESCE(json_object_agg(table_name, n), '{}') FROM (
                SELECT table_name, count(*) AS n FROM catalog_item_moves GROUP BY 1) AS g),
            'supersessions_with_moves', count(DISTINCT supersession_id),
            'first_moved', to_char(min(moved_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
            'last_moved', to_char(max(moved_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
            'moved_per_month', (SELECT COALESCE(json_object_agg(m, n), '{}') FROM (
                SELECT to_char(moved_at AT TIME ZONE 'UTC', 'YYYY-MM') AS m, count(*) AS n FROM catalog_item_moves GROUP BY 1) AS g))
        FROM catalog_item_moves),
    'admin_audit_log_identity', (
        SELECT json_build_object(
            'rows', count(*),
            'by_action', (SELECT COALESCE(json_object_agg(action, n), '{}') FROM (
                SELECT action, count(*) AS n FROM audit GROUP BY 1) AS g),
            'per_month', (SELECT COALESCE(json_object_agg(m, n), '{}') FROM (
                SELECT to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM') AS m, count(*) AS n FROM audit GROUP BY 1) AS g),
            'first', to_char(min(created_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
            'last', to_char(max(created_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
            'apply_runs', count(*) FILTER (WHERE action IN ('identity.reattach.apply', 'identity.reattach.auto')),
            'apply_run_months', count(DISTINCT to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM'))
                FILTER (WHERE action IN ('identity.reattach.apply', 'identity.reattach.auto')),
            'outcomes', (SELECT COALESCE(json_object_agg(kind, fields), '{}') FROM (
                SELECT kind, json_object_agg(field, total) AS fields FROM outcome GROUP BY kind) AS g))
        FROM audit),
    'catalog_items', (
        SELECT json_build_object(
            'rows', count(*),
            'by_kind', (SELECT COALESCE(json_object_agg(kind, n), '{}') FROM (
                SELECT kind, count(*) AS n FROM catalog_items GROUP BY 1) AS g),
            'created_per_month', (SELECT COALESCE(json_object_agg(m, n), '{}') FROM (
                SELECT to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM') AS m, count(*) AS n FROM catalog_items GROUP BY 1) AS g),
            'first_created', to_char(min(created_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
            'last_created', to_char(max(created_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD'))
        FROM catalog_items),
    'transitions', json_build_object(
        'linked_at_ingest', (SELECT COALESCE(json_object_agg(kind, n), '{}') FROM (
            SELECT item.kind, count(*) AS n
            FROM item_link JOIN catalog_items AS item ON item.id = item_link.native_id
            WHERE item_link.musicbrainz_first > item_link.discogs_first
            GROUP BY 1) AS g),
        'discogs_attached_after_musicbrainz', (SELECT COALESCE(json_object_agg(kind, n), '{}') FROM (
            SELECT item.kind, count(*) AS n
            FROM item_link JOIN catalog_items AS item ON item.id = item_link.native_id
            WHERE item_link.discogs_first > item_link.musicbrainz_first
            GROUP BY 1) AS g),
        'superseded', (SELECT COALESCE(json_object_agg(k, n), '{}') FROM (
            SELECT cause || '/' || kind AS k, count(*) AS n FROM supersession GROUP BY 1) AS g),
        'supersessions_closed', (SELECT count(*) FROM catalog_item_supersessions WHERE valid_to IS NOT NULL),
        'chain_compressed', (SELECT count(*) FROM catalog_item_supersessions WHERE via_id IS NOT NULL),
        'aliases_opened_by_supersession', (SELECT COALESCE(json_object_agg(provider, n), '{}') FROM (
            SELECT provider, count(*) AS n FROM alias WHERE opened_by_supersession GROUP BY 1) AS g),
        'aliases_closed_by_supersession', (SELECT COALESCE(json_object_agg(provider, n), '{}') FROM (
            SELECT provider, count(*) AS n FROM alias WHERE valid_to IS NOT NULL AND closed_by_supersession GROUP BY 1) AS g),
        'aliases_closed_otherwise', (SELECT COALESCE(json_object_agg(provider, n), '{}') FROM (
            SELECT provider, count(*) AS n FROM alias WHERE valid_to IS NOT NULL AND NOT closed_by_supersession GROUP BY 1) AS g),
        'aliases_opened_after_mint_otherwise', (SELECT COALESCE(json_object_agg(provider, n), '{}') FROM (
            SELECT provider, count(*) AS n FROM alias WHERE opened_after_mint AND NOT opened_by_supersession GROUP BY 1) AS g),
        'non_catalog_aliases', (SELECT COALESCE(json_object_agg(source, n), '{}') FROM (
            SELECT source, count(*) AS n FROM provider_aliases WHERE source <> 'catalog' GROUP BY 1) AS g)),
    'ledger', json_build_object(
        'editions', (SELECT count(*) FROM edition),
        'editions_with_events', (SELECT count(*) FROM edition WHERE instants >= 2),
        'editions_repaired', (SELECT count(*) FROM edition WHERE repaired),
        'editions_events_multi_month', (SELECT count(*) FROM edition WHERE months >= 2),
        'editions_by_work_count', (SELECT json_build_object(
            '0', count(*) FILTER (WHERE works = 0),
            '1', count(*) FILTER (WHERE works = 1),
            '2+', count(*) FILTER (WHERE works >= 2)) FROM work_count),
        'works', (SELECT count(*) FROM per_work),
        'works_with_2plus_evented_editions', (SELECT count(*) FROM per_work WHERE evented >= 2),
        'works_with_2plus_evented_editions_multi_month', (
            SELECT count(*) FROM per_work JOIN work_month USING (work_id) WHERE per_work.evented >= 2 AND work_month.months >= 2),
        'works_with_2plus_repaired_editions', (SELECT count(*) FROM per_work WHERE repaired >= 2),
        'evented_editions_per_work', (SELECT json_build_object(
            'p50', percentile_disc(0.5) WITHIN GROUP (ORDER BY evented),
            'p90', percentile_disc(0.9) WITHIN GROUP (ORDER BY evented),
            'p99', percentile_disc(0.99) WITHIN GROUP (ORDER BY evented),
            'max', max(evented)) FROM per_work WHERE evented >= 1),
        'split_now', (SELECT count(*) FROM mb_link
            WHERE musicbrainz_native_id IS NOT NULL AND discogs_native_id IS NOT NULL AND musicbrainz_native_id <> discogs_native_id),
        'unresolved_now', (SELECT count(*) FROM mb_link WHERE discogs_native_id IS NULL))
);
