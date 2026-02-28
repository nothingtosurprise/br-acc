#!/usr/bin/env python3
"""Run global temporal integrity gates plus source-specific gate packs."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass

from neo4j import GraphDatabase


@dataclass(frozen=True)
class Gate:
    name: str
    query: str
    operator: str
    expected: int


GLOBAL_GATES: list[Gate] = [
    Gate(
        name="global_temporal_invalid_edges_count",
        query=(
            "MATCH ()-[r]->() "
            "WHERE r.temporal_status = 'invalid' "
            "RETURN count(r) AS value"
        ),
        operator="eq",
        expected=0,
    ),
    Gate(
        name="global_temporal_unknown_edges_count",
        query=(
            "MATCH ()-[r]->() "
            "WHERE r.temporal_status = 'unknown' "
            "RETURN count(r) AS value"
        ),
        operator="lte",
        expected=100000,
    ),
]


def _passes(operator: str, value: int, expected: int) -> bool:
    if operator == "eq":
        return value == expected
    if operator == "gt":
        return value > expected
    if operator == "gte":
        return value >= expected
    if operator == "lt":
        return value < expected
    if operator == "lte":
        return value <= expected
    raise ValueError(f"Unsupported operator: {operator}")


def _describe(operator: str, expected: int) -> str:
    if operator == "eq":
        return f"== {expected}"
    if operator == "gt":
        return f"> {expected}"
    if operator == "gte":
        return f">= {expected}"
    if operator == "lt":
        return f"< {expected}"
    if operator == "lte":
        return f"<= {expected}"
    return str(expected)


def _run_global(uri: str, user: str, database: str, password: str, unknown_max: int) -> int:
    gates = [
        gate if gate.name != "global_temporal_unknown_edges_count"
        else Gate(
            name=gate.name,
            query=gate.query,
            operator=gate.operator,
            expected=unknown_max,
        )
        for gate in GLOBAL_GATES
    ]
    driver = GraphDatabase.driver(uri, auth=(user, password))
    failed = 0
    try:
        with driver.session(database=database) as session:
            for gate in gates:
                value = int(session.run(gate.query).single()["value"])
                ok = _passes(gate.operator, value, gate.expected)
                status = "PASS" if ok else "FAIL"
                expectation = _describe(gate.operator, gate.expected)
                print(
                    f"[{status}] {gate.name}: value={value} expected {expectation}"
                )
                if not ok:
                    failed += 1
    finally:
        driver.close()
    return failed


def _run_senado_subgate(
    uri: str,
    user: str,
    database: str,
    password_env: str,
    unknown_max: int,
) -> int:
    cmd = [
        "python3",
        "scripts/run_senado_temporal_gates.py",
        "--uri",
        uri,
        "--user",
        user,
        "--database",
        database,
        "--password-env",
        password_env,
        "--unknown-max",
        str(unknown_max),
    ]
    result = subprocess.run(cmd, check=False)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", required=True, help="Neo4j bolt URI")
    parser.add_argument("--user", default="neo4j", help="Neo4j username")
    parser.add_argument("--database", default="neo4j", help="Neo4j database name")
    parser.add_argument(
        "--password-env",
        default="NEO4J_PASSWORD",
        help="Environment variable containing Neo4j password",
    )
    parser.add_argument(
        "--global-unknown-max",
        type=int,
        default=100000,
        help="Max allowed unknown temporal edges globally.",
    )
    parser.add_argument(
        "--senado-unknown-max",
        type=int,
        default=5000,
        help="Max allowed unknown temporal edges for Senado-specific gate pack.",
    )
    parser.add_argument(
        "--skip-senado",
        action="store_true",
        help="Run only global temporal gates.",
    )
    args = parser.parse_args()

    password = os.getenv(args.password_env, "")
    if not password:
        print(f"[ERROR] Missing password in env var: {args.password_env}")
        return 2

    failed = _run_global(
        uri=args.uri,
        user=args.user,
        database=args.database,
        password=password,
        unknown_max=args.global_unknown_max,
    )
    if not args.skip_senado:
        senado_rc = _run_senado_subgate(
            uri=args.uri,
            user=args.user,
            database=args.database,
            password_env=args.password_env,
            unknown_max=args.senado_unknown_max,
        )
        if senado_rc != 0:
            failed += 1

    if failed:
        print(f"[SUMMARY] Temporal gates failed ({failed} failing block(s)).")
        return 1
    print("[SUMMARY] Temporal gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
