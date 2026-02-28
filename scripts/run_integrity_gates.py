#!/usr/bin/env python3
"""Run hard integrity gates against Neo4j and return pass/fail."""

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
    operator: str  # one of: eq, gt
    expected: int


GATES: list[Gate] = [
    Gate(
        name="person_cpf_masked",
        query="MATCH (p:Person) WHERE p.cpf CONTAINS '*' RETURN count(p) AS value",
        operator="eq",
        expected=0,
    ),
    Gate(
        name="person_cpf_14_digits",
        query=(
            "MATCH (p:Person) "
            "WHERE replace(replace(p.cpf, '.', ''), '-', '') =~ '\\\\d{14}' "
            "RETURN count(p) AS value"
        ),
        operator="eq",
        expected=0,
    ),
    Gate(
        name="invalid_person_company_socio_links",
        query=(
            "MATCH (p:Person)-[:SOCIO_DE]->(:Company) "
            "WHERE NOT p.cpf =~ '\\\\d{3}\\\\.\\\\d{3}\\\\.\\\\d{3}-\\\\d{2}' "
            "RETURN count(p) AS value"
        ),
        operator="eq",
        expected=0,
    ),
    Gate(
        name="company_company_socio_links",
        query="MATCH (:Company)-[r:SOCIO_DE]->(:Company) RETURN count(r) AS value",
        operator="gt",
        expected=0,
    ),
    Gate(
        name="partner_company_socio_links",
        query="MATCH (:Partner)-[r:SOCIO_DE]->(:Company) RETURN count(r) AS value",
        operator="gt",
        expected=0,
    ),
    Gate(
        name="partial_doc_same_as_edges",
        query=(
            "MATCH ()-[r:SAME_AS]-() "
            "WHERE r.method = 'partial_cpf_name_match' "
            "RETURN count(r) AS value"
        ),
        operator="eq",
        expected=0,
    ),
]


def _passes(operator: str, value: int, expected: int) -> bool:
    if operator == "eq":
        return value == expected
    if operator == "gt":
        return value > expected
    raise ValueError(f"Unsupported operator: {operator}")


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
    args = parser.parse_args()

    password = os.getenv(args.password_env, "")
    if not password:
        print(f"[ERROR] Missing password in env var: {args.password_env}")
        return 2

    driver = GraphDatabase.driver(args.uri, auth=(args.user, password))
    failed = 0
    try:
        with driver.session(database=args.database) as session:
            for gate in GATES:
                value = int(session.run(gate.query).single()["value"])
                ok = _passes(gate.operator, value, gate.expected)
                status = "PASS" if ok else "FAIL"
                expected_desc = (
                    f"== {gate.expected}" if gate.operator == "eq" else f"> {gate.expected}"
                )
                print(f"[{status}] {gate.name}: value={value} expected {expected_desc}")
                if not ok:
                    failed += 1
    finally:
        driver.close()

    if failed:
        print(f"[SUMMARY] {failed} gate(s) failed.")
        return 1

    print("[SUMMARY] All integrity gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
