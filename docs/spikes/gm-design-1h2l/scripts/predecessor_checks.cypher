// SPDX-License-Identifier: MIT
// Read-only checks run against the predecessor graph, aggregates only:
//   <read-only cypher-shell wrapper> 300 < predecessor_checks.cypher
// Each statement is bounded: count-store reads, index seeks, or degree reads.
CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition;
SHOW CONSTRAINTS YIELD name, type, labelsOrTypes, properties RETURN name, type, labelsOrTypes, properties ORDER BY name;
SHOW INDEXES YIELD name, type, entityType, labelsOrTypes, properties, state RETURN name, type, entityType, labelsOrTypes, properties, state ORDER BY name;
CALL dbms.listConfig() YIELD name, value WHERE name IN ['server.memory.heap.max_size', 'server.memory.pagecache.size', 'db.transaction.timeout'] RETURN name, value;
CALL dbms.queryJmx('java.lang:type=OperatingSystem') YIELD attributes RETURN attributes.AvailableProcessors.value AS cpus, attributes.TotalMemorySize.value AS memory_bytes;
MATCH (n:Release) RETURN count(n) AS releases;
MATCH (n:Master) RETURN count(n) AS masters;
MATCH ()-[r:BY]->() RETURN count(r) AS by_edges;
MATCH ()-[r:DERIVED_FROM]->() RETURN count(r) AS derived_from_edges;
MATCH ()-[r:CREDITED_ON]->() RETURN count(r) AS credited_on_edges;
// The Discogs "no master" sentinel, if the enricher kept it.
MATCH (m:Master {id: '0'}) RETURN count(m) AS zero_master, COUNT { (m)<-[:DERIVED_FROM]-() } AS zero_master_releases;
// The largest roots a strata query can start from.
MATCH (a:Artist) WITH COUNT { (a)<-[:BY]-() } AS d ORDER BY d DESC LIMIT 5 RETURN collect(d) AS top_by_degrees;
// Collector edges and their recorded time.
MATCH (u:User) RETURN count(u) AS users,
  sum(COUNT { (u)-[:COLLECTED]->() }) AS collected,
  sum(COUNT { (u)-[c:COLLECTED]->() WHERE c.date_added IS NOT NULL }) AS collected_with_date_added,
  sum(COUNT { (u)-[:WANTS]->() }) AS wants,
  sum(COUNT { (u)-[w:WANTS]->() WHERE w.date_added IS NOT NULL }) AS wants_with_date_added;
