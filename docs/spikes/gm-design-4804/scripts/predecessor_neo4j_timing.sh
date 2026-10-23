#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Time the style-by-year aggregation a live lifecycle route would need, on the
# predecessor deployment's full Neo4j graph (read-only, maintainer-authorized). Predecessor
# schema: same Release, Style, Genre labels, IS relationship, and Release.year property as
# catalog-api's queries read. The aggregate is wrapped in count/sum so only two numbers
# cross the wire. Each query is capped at 300 s; a timeout is recorded, never retried.
# CYPHER_CMD is a command that runs stdin as a READ-mode Cypher transaction and takes the
# timeout in seconds as its first argument.
# Usage: CYPHER_CMD=<read-only cypher runner> predecessor_neo4j_timing.sh > results/predecessor_neo4j.json
set -uo pipefail
: "${CYPHER_CMD:?}"
STYLE_YEAR='MATCH (r:Release)-[:IS]->(s:Style)
WHERE r.year IS NOT NULL AND r.year > 0
WITH s.name AS style, r.year AS year, count(r) AS release_count
RETURN count(*) AS cells, sum(release_count) AS tagged_releases;'
GENRE_DECADE='MATCH (r:Release)-[:IS]->(g:Genre)
WHERE r.year IS NOT NULL AND r.year > 0
WITH g.name AS genre, (r.year / 10) * 10 AS decade, count(r) AS release_count
RETURN count(*) AS cells, sum(release_count) AS tagged_releases;'
run() {  # name query -> one JSON object
  local start end out rc tmp
  tmp=$(mktemp)
  start=$(date +%s.%N)
  printf '%s\n' "$2" | $CYPHER_CMD 300 > "$tmp" 2>/dev/null
  rc=$?
  end=$(date +%s.%N)
  out=$(tail -1 "$tmp")
  rm -f "$tmp"
  printf '{"query":"%s","rc":%s,"wall_s":%.2f,"result":"%s"}' "$1" "$rc" "$(echo "$end - $start" | bc)" "$out"
}
echo "{\"runs\":["
run overhead 'RETURN 1 AS one;'; echo ","
run overhead 'RETURN 1 AS one;'; echo ","
run style_by_year "$STYLE_YEAR"; echo ","
run style_by_year "$STYLE_YEAR"; echo ","
run genre_by_decade "$GENRE_DECADE"
echo "]}"
