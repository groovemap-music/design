# SPDX-License-Identifier: MIT
"""The latency harness's Cypher, run against a throwaway, empty Neo4j.

Skipped unless GM_SPIKE_NEO4J_URI names one (see the README). The test writes an
invented graph, so it refuses any database that already holds a node: it can never
touch a real catalog. It checks that every query parses and that the strata ladder
returns the planes the payload rule needs. It measures nothing.
"""
import os

import pytest

neo4j = pytest.importorskip("neo4j")

from latency import ANONYMOUS, QUERIES, params_for  # noqa: E402

URI = os.environ.get("GM_SPIKE_NEO4J_URI")
pytestmark = pytest.mark.skipif(not URI, reason="GM_SPIKE_NEO4J_URI is not set")

GRAPH = """
CREATE (a:Artist {id: '1', name: 'Alpha Unit'}), (b:Artist {id: '2', name: 'Beta Ensemble'}),
       (g:Artist {id: '3', name: 'Alpha Group'}), (l:Label {id: '9', name: 'Label'}),
       (m1:Master {id: '501', title: 'First Light', year: 1971}),
       (m2:Master {id: '502', title: 'Second', year: 1975}),
       (r1:Release {id: '11', title: 'First Light', year: 1971}),
       (r2:Release {id: '12', title: 'First Light (Reissue)', year: 1999}),
       (r3:Release {id: '13', title: 'Second', year: 1975}),
       (r4:Release {id: '14', title: 'Loose Single', year: 0}),
       (u:User {id: 'u-1'}),
       (r1)-[:BY]->(a), (r1)-[:BY]->(b), (r2)-[:BY]->(a), (r3)-[:BY]->(a), (r4)-[:BY]->(a),
       (r1)-[:DERIVED_FROM]->(m1), (r2)-[:DERIVED_FROM]->(m1), (r3)-[:DERIVED_FROM]->(m2),
       (r1)-[:ON]->(l), (a)-[:MEMBER_OF]->(g),
       (u)-[:COLLECTED {instance_id: '1', date_added: '2019-05-01T10:00:00-07:00'}]->(r2), (u)-[:WANTS {date_added: '2021-01-02T03:04:05-08:00'}]->(r3)
"""


@pytest.fixture(scope="module")
def session():
    driver = neo4j.GraphDatabase.driver(URI, auth=(os.environ.get("GM_SPIKE_NEO4J_USER", "neo4j"), os.environ.get("GM_SPIKE_NEO4J_PASSWORD", "")))
    with driver.session() as s:
        if s.run("MATCH (n) RETURN count(n) AS n").single()["n"]:
            pytest.skip("refusing a non-empty database")
        s.run(GRAPH).consume()
        yield s
        s.run("MATCH (n) DETACH DELETE n").consume()
    driver.close()


def test_every_query_runs(session):
    for name, (cypher, _) in QUERIES.items():
        rows = session.run(cypher, params_for(name, "1", "Alpha Unit")).data()
        assert rows, name


def test_strata_ladder_shape(session):
    params = params_for("strata_ladder", "1", "Alpha Unit")
    rows = {r["master_id"]: r for r in session.run(QUERIES["strata_ladder"][0], params).data()}
    assert set(rows) == {"501", "502", None}
    assert rows["501"]["releases"] == 2 and rows[None]["releases"] == 1
    assert all(not s["marks"] for r in rows.values() for s in r["sample"])  # anonymous
    params["user_id"] = "u-1"
    rows = {r["master_id"]: r for r in session.run(QUERIES["strata_ladder"][0], params).data()}
    marks = {s["id"]: s["marks"] for r in rows.values() for s in r["sample"]}
    assert marks["12"] == [{"kind": "COLLECTED", "date_added": "2019-05-01T10:00:00-07:00"}]
    assert marks["13"] == [{"kind": "WANTS", "date_added": "2021-01-02T03:04:05-08:00"}]
    assert marks["11"] == []
    assert params_for("strata_ladder", "1", "x")["user_id"] == ANONYMOUS


def test_strata_credits_shape(session):
    row = session.run(QUERIES["strata_credits"][0], params_for("strata_credits", "1", "Alpha Unit")).single()
    assert [j["id"] for j in row["joint"]] == ["2"]
    assert [(r["id"], r["rel"]) for r in row["related"]] == [("3", "MEMBER_OF")]
