-- SPDX-License-Identifier: MIT
-- The tables sql/identity_history.sql reads, for tests/test_sql_parity.py only.
--
-- Column definitions are copied from database-schema `src/groovemap_schema/postgres.py` at
-- 817081d (2026-10-19), not imported. Foreign keys to `users` are dropped, because the
-- parity fixture has no users and the measurement never reads a user or admin id. The
-- provider-keyed tables keep only the columns the measurement reads. Never run this against
-- a catalog: it is for a scratch database the parity test creates and drops.
CREATE TABLE catalog_items (
    id         UUID PRIMARY KEY,
    kind       TEXT NOT NULL CHECK (kind IN ('release', 'master', 'artist', 'label')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE provider_aliases (
    id          UUID PRIMARY KEY,
    provider    TEXT NOT NULL,
    entity_kind TEXT NOT NULL,
    external_id TEXT NOT NULL,
    native_id   UUID NOT NULL,
    valid_from  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_to    TIMESTAMPTZ,
    confidence  REAL NOT NULL DEFAULT 1.0,
    source      TEXT NOT NULL DEFAULT 'catalog',
    asserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_provider_aliases_provider_entity_kind_external_id
    ON provider_aliases (provider, entity_kind, external_id) WHERE valid_to IS NULL;

CREATE TABLE catalog_item_supersessions (
    id            UUID PRIMARY KEY,
    superseded_id UUID NOT NULL REFERENCES catalog_items(id),
    survivor_id   UUID NOT NULL REFERENCES catalog_items(id),
    cause         TEXT NOT NULL CHECK (cause IN ('edition_promotion', 'catalog_reattachment')),
    decision_ref  UUID NOT NULL,
    valid_from    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_to      TIMESTAMPTZ,
    via_id        UUID REFERENCES catalog_item_supersessions(id),
    CONSTRAINT catalog_item_supersessions_distinct_items CHECK (superseded_id <> survivor_id)
);
CREATE UNIQUE INDEX idx_catalog_item_supersessions_superseded_id
    ON catalog_item_supersessions (superseded_id) WHERE valid_to IS NULL;

CREATE TABLE catalog_item_moves (
    id              UUID PRIMARY KEY,
    supersession_id UUID NOT NULL REFERENCES catalog_item_supersessions(id),
    table_name      TEXT NOT NULL CHECK (table_name IN ('artifacts', 'owned_copies')),
    row_id          UUID NOT NULL,
    from_item_id    UUID NOT NULL REFERENCES catalog_items(id),
    to_item_id      UUID NOT NULL REFERENCES catalog_items(id),
    user_id         UUID,
    moved_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT catalog_item_moves_supersession_row_key UNIQUE (supersession_id, table_name, row_id)
);

CREATE TABLE admin_audit_log (
    id         UUID PRIMARY KEY,
    admin_id   UUID NOT NULL,
    action     VARCHAR(100) NOT NULL,
    target     VARCHAR(255),
    details    JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE releases (
    data_id VARCHAR PRIMARY KEY,
    data    JSONB NOT NULL
);

CREATE SCHEMA musicbrainz;
CREATE TABLE musicbrainz.releases (
    mbid               UUID PRIMARY KEY,
    release_group_mbid UUID,
    discogs_release_id BIGINT
);
