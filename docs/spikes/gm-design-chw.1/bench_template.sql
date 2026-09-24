\set ON_ERROR_STOP on
\timing on

DROP TABLE IF EXISTS bench_items;
CREATE TABLE bench_items (id bigint primary key, embedding halfvec(__DIM__));
INSERT INTO bench_items SELECT g, random_halfvec(__DIM__) FROM generate_series(1,__ROWS__) g;
VACUUM ANALYZE bench_items;

-- === index build (timed by \timing; wrapped with markers for grep) ===
\echo BUILD_START
CREATE INDEX bench_idx ON bench_items USING hnsw (embedding halfvec_cosine_ops);
\echo BUILD_END

\echo SIZE_MARKER
SELECT pg_relation_size('bench_idx') AS index_bytes, pg_total_relation_size('bench_items') AS table_total_bytes;

-- === query set ===
DROP TABLE IF EXISTS bench_queries;
CREATE TEMP TABLE bench_queries AS SELECT g AS qid, random_halfvec(__DIM__) AS embedding FROM generate_series(1,100) g;

-- === exact top-10 (force seqscan) ===
SET enable_indexscan = off;
SET enable_bitmapscan = off;
DROP TABLE IF EXISTS bench_exact;
CREATE TEMP TABLE bench_exact AS
SELECT q.qid, i.id
FROM bench_queries q CROSS JOIN LATERAL (
  SELECT id FROM bench_items ORDER BY embedding <=> q.embedding LIMIT 10
) i;
RESET enable_indexscan;
RESET enable_bitmapscan;

-- === approx recall @ ef_search=40 ===
SET hnsw.ef_search = 40;
DROP TABLE IF EXISTS bench_approx40;
CREATE TEMP TABLE bench_approx40 AS
SELECT q.qid, i.id
FROM bench_queries q CROSS JOIN LATERAL (
  SELECT id FROM bench_items ORDER BY embedding <=> q.embedding LIMIT 10
) i;

-- === approx recall @ ef_search=100 ===
SET hnsw.ef_search = 100;
DROP TABLE IF EXISTS bench_approx100;
CREATE TEMP TABLE bench_approx100 AS
SELECT q.qid, i.id
FROM bench_queries q CROSS JOIN LATERAL (
  SELECT id FROM bench_items ORDER BY embedding <=> q.embedding LIMIT 10
) i;

\echo RECALL_MARKER
SELECT
  (SELECT count(*)::numeric FROM bench_exact e JOIN bench_approx40 a ON e.qid=a.qid AND e.id=a.id) / 1000.0 AS recall_at_10_ef40,
  (SELECT count(*)::numeric FROM bench_exact e JOIN bench_approx100 a ON e.qid=a.qid AND e.id=a.id) / 1000.0 AS recall_at_10_ef100;

-- === latency, ef_search=100, no filter ===
SET hnsw.ef_search = 100;
DROP TABLE IF EXISTS bench_lat_nofilter;
CREATE TEMP TABLE bench_lat_nofilter(qid int, ms double precision);
DO $$
DECLARE r record; t0 timestamptz; t1 timestamptz;
BEGIN
  FOR r IN SELECT qid, embedding FROM bench_queries LOOP
    t0 := clock_timestamp();
    PERFORM id FROM bench_items ORDER BY embedding <=> r.embedding LIMIT 10;
    t1 := clock_timestamp();
    INSERT INTO bench_lat_nofilter VALUES (r.qid, extract(epoch FROM (t1-t0))*1000);
  END LOOP;
END $$;

\echo LATENCY_NOFILTER_MARKER
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) AS p50_ms,
       percentile_cont(0.99) WITHIN GROUP (ORDER BY ms) AS p99_ms
FROM bench_lat_nofilter;

-- === latency, ef_search=100, filtered (10% selectivity), iterative scan on ===
SET hnsw.iterative_scan = relaxed_order;
DROP TABLE IF EXISTS bench_lat_filter;
CREATE TEMP TABLE bench_lat_filter(qid int, ms double precision);
DO $$
DECLARE r record; t0 timestamptz; t1 timestamptz;
BEGIN
  FOR r IN SELECT qid, embedding FROM bench_queries LOOP
    t0 := clock_timestamp();
    PERFORM id FROM bench_items WHERE id % 10 = 0 ORDER BY embedding <=> r.embedding LIMIT 10;
    t1 := clock_timestamp();
    INSERT INTO bench_lat_filter VALUES (r.qid, extract(epoch FROM (t1-t0))*1000);
  END LOOP;
END $$;
RESET hnsw.iterative_scan;

\echo LATENCY_FILTER_MARKER
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) AS p50_ms,
       percentile_cont(0.99) WITHIN GROUP (ORDER BY ms) AS p99_ms
FROM bench_lat_filter;

-- === insert / update cost ===
\echo INSERT_COST_MARKER
DO $$
DECLARE t0 timestamptz; t1 timestamptz; i int;
BEGIN
  DROP TABLE IF EXISTS bench_ins_cost;
  CREATE TEMP TABLE bench_ins_cost(ms double precision);
  FOR i IN 1..200 LOOP
    t0 := clock_timestamp();
    INSERT INTO bench_items VALUES (__ROWS__ + i, random_halfvec(__DIM__));
    t1 := clock_timestamp();
    INSERT INTO bench_ins_cost VALUES (extract(epoch FROM (t1-t0))*1000);
  END LOOP;
END $$;
SELECT avg(ms) AS avg_insert_ms, percentile_cont(0.99) WITHIN GROUP (ORDER BY ms) AS p99_insert_ms FROM bench_ins_cost;

\echo UPDATE_COST_MARKER
DO $$
DECLARE t0 timestamptz; t1 timestamptz; i int;
BEGIN
  DROP TABLE IF EXISTS bench_upd_cost;
  CREATE TEMP TABLE bench_upd_cost(ms double precision);
  FOR i IN 1..200 LOOP
    t0 := clock_timestamp();
    UPDATE bench_items SET embedding = random_halfvec(__DIM__) WHERE id = i;
    t1 := clock_timestamp();
    INSERT INTO bench_upd_cost VALUES (extract(epoch FROM (t1-t0))*1000);
  END LOOP;
END $$;
SELECT avg(ms) AS avg_update_ms, percentile_cont(0.99) WITHIN GROUP (ORDER BY ms) AS p99_update_ms FROM bench_upd_cost;

\echo DONE_MARKER
