#!/usr/bin/env python3
"""Run Senado CPI/CPMI temporal gates against Neo4j."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

from neo4j import GraphDatabase


@dataclass(frozen=True)
class Gate:
    name: str
    query: str
    operator: str  # eq, gt, gte, lte
    expected: int


def _build_gates(unknown_max: int) -> list[Gate]:
    return [
        Gate(
            name="senado_inquiry_count",
            query="MATCH (i:Inquiry {source: 'senado_cpis'}) RETURN count(i) AS value",
            operator="gt",
            expected=3,
        ),
        Gate(
            name="senado_requirements_count",
            query=(
                "MATCH (r:InquiryRequirement {source: 'senado_cpis'}) "
                "RETURN count(r) AS value"
            ),
            operator="gt",
            expected=200,
        ),
        Gate(
            name="senado_sessions_count",
            query=(
                "MATCH (s:InquirySession {source: 'senado_cpis'}) "
                "RETURN count(s) AS value"
            ),
            operator="gt",
            expected=0,
        ),
        Gate(
            name="senado_fallback_rows_count",
            query=(
                "MATCH (i:Inquiry {source: 'senado_cpis'}) "
                "WHERE i.inquiry_id = 'senado-cpmi-inss-2026' "
                "RETURN count(i) AS value"
            ),
            operator="eq",
            expected=0,
        ),
        Gate(
            name="senado_temporal_invalid_edges_count",
            query=(
                "MATCH (i:Inquiry {source: 'senado_cpis'})"
                "-[r:TEM_REQUERIMENTO|REALIZOU_SESSAO]->() "
                "WHERE r.temporal_status = 'invalid' "
                "RETURN count(r) AS value"
            ),
            operator="eq",
            expected=0,
        ),
        Gate(
            name="senado_temporal_unknown_edges_count",
            query=(
                "MATCH (i:Inquiry {source: 'senado_cpis'})"
                "-[r:TEM_REQUERIMENTO|REALIZOU_SESSAO]->() "
                "WHERE r.temporal_status = 'unknown' "
                "RETURN count(r) AS value"
            ),
            operator="lte",
            expected=unknown_max,
        ),
    ]


def _passes(operator: str, value: int, expected: int) -> bool:
    if operator == "eq":
        return value == expected
    if operator == "gt":
        return value > expected
    if operator == "gte":
        return value >= expected
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
    if operator == "lte":
        return f"<= {expected}"
    return str(expected)


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
        "--unknown-max",
        type=int,
        default=5000,
        help="Max allowed unknown temporal edges before failing.",
    )
    args = parser.parse_args()

    password = os.getenv(args.password_env, "")
    if not password:
        print(f"[ERROR] Missing password in env var: {args.password_env}")
        return 2

    gates = _build_gates(unknown_max=args.unknown_max)
    driver = GraphDatabase.driver(args.uri, auth=(args.user, password))
    failed = 0

    try:
        with driver.session(database=args.database) as session:
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

    if failed:
        print(f"[SUMMARY] {failed} Senado temporal gate(s) failed.")
        return 1

    print("[SUMMARY] All Senado temporal gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
