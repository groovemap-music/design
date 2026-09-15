#!/usr/bin/env python3
"""Exercise malformed query, parameter, and result shapes at real database engines."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any


async def probe_postgres() -> dict[str, Any]:
    import psycopg

    connection = await psycopg.AsyncConnection.connect(os.environ["AUDIT_DATABASE_URL"])
    killed = []
    try:
        try:
            await connection.execute("SELEC 1")
        except psycopg.errors.SyntaxError:
            killed.append("malformed-postgresql-query")
        else:
            raise AssertionError("malformed PostgreSQL query survived")
        await connection.rollback()

        try:
            await connection.execute("SELECT %s::uuid", ("not-a-uuid",))
        except psycopg.errors.InvalidTextRepresentation:
            killed.append("malformed-postgresql-parameter")
        else:
            raise AssertionError("malformed PostgreSQL parameter survived")
        await connection.rollback()
    finally:
        await connection.close()
    return {"engine": "postgresql", "mutations_killed": killed}


async def probe_neo4j() -> dict[str, Any]:
    from neo4j import AsyncGraphDatabase
    from neo4j.exceptions import CypherSyntaxError, ResultNotSingleError

    driver = AsyncGraphDatabase.driver(
        os.environ["AUDIT_NEO4J_URI"],
        auth=("neo4j", os.environ["AUDIT_NEO4J_PASSWORD"]),
    )
    killed = []
    try:
        await driver.verify_connectivity()
        async with driver.session(database="neo4j") as session:
            try:
                result = await session.run("RETUR 1 AS value")
                await result.consume()
            except CypherSyntaxError:
                killed.append("malformed-neo4j-query")
            else:
                raise AssertionError("malformed Neo4j query survived")

            result = await session.run("UNWIND [1, 2] AS value RETURN value")
            try:
                await result.single(strict=True)
            except ResultNotSingleError:
                killed.append("malformed-neo4j-result-shape")
            else:
                raise AssertionError("multi-row Neo4j result survived strict result validation")
    finally:
        await driver.close()
    return {"engine": "neo4j", "mutations_killed": killed}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("engine", choices=("postgresql", "neo4j"))
    args = parser.parse_args()
    result = await (probe_postgres() if args.engine == "postgresql" else probe_neo4j())
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
