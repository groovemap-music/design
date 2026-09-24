\set qid random(1,1000000)
SELECT id FROM bench_items ORDER BY embedding <=> (SELECT embedding FROM bench_items WHERE id = :qid) LIMIT 10;
