#!/usr/bin/env python3
"""Validate Brazil source registry completeness and code alignment."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REQUIRED_COLUMNS = {
    "source_id",
    "name",
    "category",
    "tier",
    "status",
    "implementation_state",
    "load_state",
    "frequency",
    "in_universe_v1",
    "primary_url",
    "pipeline_id",
    "owner_agent",
    "access_mode",
    "public_access_mode",
    "discovery_status",
    "last_seen_url",
    "cadence_expected",
    "cadence_observed",
    "quality_status",
    "notes",
}

VALID_STATUS = {
    "loaded",
    "partial",
    "stale",
    "blocked_external",
    "quality_fail",
    "not_built",
}
VALID_IMPLEMENTATION = {"implemented", "not_implemented"}
VALID_LOAD_STATE = {"loaded", "partial", "not_loaded"}
VALID_DISCOVERY_STATUS = {
    "discovered",
    "discovered_uningested",
    "monitored",
    "unreachable",
}
VALID_QUALITY_STATUS = {
    "loaded",
    "healthy",
    "partial",
    "stale",
    "blocked_external",
    "quality_fail",
    "not_built",
}
PIPELINE_ENTRY_RE = re.compile(r'^\s*"([a-z0-9_]+)":\s*[A-Za-z_][A-Za-z0-9_]*,\s*$')


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    details: str


def parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def read_registry(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], [f"registry file not found: {path}"]

    with path.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        missing_cols = REQUIRED_COLUMNS.difference(set(reader.fieldnames or []))
        if missing_cols:
            return [], [f"missing required columns: {sorted(missing_cols)}"]
        rows = list(reader)
    return rows, []


def parse_runner_pipelines(path: Path) -> tuple[set[str], list[str]]:
    if not path.exists():
        return set(), [f"runner file not found: {path}"]

    pipelines: set[str] = set()
    inside_map = False
    with path.open(encoding="utf-8") as runner_file:
        for raw_line in runner_file:
            line = raw_line.rstrip("\n")
            if line.startswith("PIPELINES: dict[str, type] = {"):
                inside_map = True
                continue
            if inside_map and line.strip() == "}":
                break
            if inside_map:
                match = PIPELINE_ENTRY_RE.match(line)
                if match:
                    pipelines.add(match.group(1))
    if not pipelines:
        return set(), ["could not parse pipeline ids from runner"]
    return pipelines, []


def build_gate_results(
    rows: list[dict[str, str]],
    runner_pipelines: set[str],
    expected_universe: int,
    expected_implemented: int,
) -> tuple[list[GateResult], dict[str, int], dict[str, int]]:
    source_ids = [row["source_id"].strip() for row in rows]
    duplicate_ids = [sid for sid, count in Counter(source_ids).items() if count > 1]
    invalid_status = sorted(
        {
            row["status"].strip()
            for row in rows
            if row["status"].strip() and row["status"].strip() not in VALID_STATUS
        }
    )
    invalid_implementation = sorted(
        {
            row["implementation_state"].strip()
            for row in rows
            if row["implementation_state"].strip()
            and row["implementation_state"].strip() not in VALID_IMPLEMENTATION
        }
    )
    invalid_load_state = sorted(
        {
            row["load_state"].strip()
            for row in rows
            if row["load_state"].strip() and row["load_state"].strip() not in VALID_LOAD_STATE
        }
    )
    invalid_discovery_status = sorted(
        {
            str(row.get("discovery_status") or "").strip()
            for row in rows
            if str(row.get("discovery_status") or "").strip()
            and str(row.get("discovery_status") or "").strip() not in VALID_DISCOVERY_STATUS
        }
    )
    invalid_quality_status = sorted(
        {
            str(row.get("quality_status") or "").strip()
            for row in rows
            if str(row.get("quality_status") or "").strip()
            and str(row.get("quality_status") or "").strip() not in VALID_QUALITY_STATUS
        }
    )

    universe_rows = [row for row in rows if parse_bool(row["in_universe_v1"])]
    implemented_rows = [
        row for row in universe_rows if row["implementation_state"].strip() == "implemented"
    ]
    implemented_ids = {row["source_id"].strip() for row in implemented_rows}

    status_counter = Counter(row["status"].strip() for row in universe_rows)
    implementation_counter = Counter(
        row["implementation_state"].strip() for row in universe_rows
    )

    missing_from_registry = sorted(runner_pipelines - implemented_ids)
    not_in_runner = sorted(implemented_ids - runner_pipelines)

    gates = [
        GateResult(
            name="registry_has_no_duplicate_source_ids",
            passed=not duplicate_ids,
            details=f"duplicates={duplicate_ids}" if duplicate_ids else "ok",
        ),
        GateResult(
            name="registry_values_are_valid",
            passed=(
                not invalid_status
                and not invalid_implementation
                and not invalid_load_state
                and not invalid_discovery_status
                and not invalid_quality_status
            ),
            details=(
                f"invalid_status={invalid_status}; "
                f"invalid_implementation={invalid_implementation}; "
                f"invalid_load_state={invalid_load_state}; "
                f"invalid_discovery_status={invalid_discovery_status}; "
                f"invalid_quality_status={invalid_quality_status}"
            ),
        ),
        GateResult(
            name="universe_v1_count_matches_expected",
            passed=len(universe_rows) == expected_universe,
            details=f"actual={len(universe_rows)} expected={expected_universe}",
        ),
        GateResult(
            name="implemented_count_matches_expected",
            passed=len(implemented_rows) == expected_implemented,
            details=f"actual={len(implemented_rows)} expected={expected_implemented}",
        ),
        GateResult(
            name="runner_pipelines_are_all_marked_implemented",
            passed=not missing_from_registry,
            details=f"missing={missing_from_registry}" if missing_from_registry else "ok",
        ),
        GateResult(
            name="implemented_registry_ids_exist_in_runner",
            passed=not not_in_runner,
            details=f"extra={not_in_runner}" if not_in_runner else "ok",
        ),
    ]
    return gates, dict(status_counter), dict(implementation_counter)


def write_outputs(
    output_dir: Path,
    registry_path: Path,
    runner_path: Path,
    expected_universe: int,
    expected_implemented: int,
    gates: list[GateResult],
    status_counter: dict[str, int],
    implementation_counter: dict[str, int],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "registry_path": str(registry_path),
        "runner_path": str(runner_path),
        "expected_universe_v1": expected_universe,
        "expected_implemented": expected_implemented,
        "status_counter": status_counter,
        "implementation_counter": implementation_counter,
        "gates": [gate.__dict__ for gate in gates],
        "all_passed": all(gate.passed for gate in gates),
    }
    (output_dir / "source_completeness_report.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Source Completeness Gate Report",
        "",
        f"- Timestamp (UTC): `{payload['timestamp_utc']}`",
        f"- Registry: `{registry_path}`",
        f"- Runner: `{runner_path}`",
        f"- Expected universe_v1: `{expected_universe}`",
        f"- Expected implemented: `{expected_implemented}`",
        "",
        "## Counters",
        "",
        f"- status_counter: `{status_counter}`",
        f"- implementation_counter: `{implementation_counter}`",
        "",
        "## Gate Results",
        "",
    ]
    for gate in gates:
        mark = "PASS" if gate.passed else "FAIL"
        lines.append(f"- `{mark}` `{gate.name}`: {gate.details}")
    lines.append("")
    lines.append(f"## Final: `{'PASS' if payload['all_passed'] else 'FAIL'}`")
    lines.append("")
    (output_dir / "source_completeness_report.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate source registry completeness and code alignment."
    )
    parser.add_argument(
        "--registry-path",
        default="docs/source_registry_br_v1.csv",
        help="Path to source registry CSV",
    )
    parser.add_argument(
        "--runner-path",
        default="etl/src/icarus_etl/runner.py",
        help="Path to ETL runner with PIPELINES map",
    )
    parser.add_argument(
        "--expected-universe-v1",
        type=int,
        default=108,
        help="Expected count for in_universe_v1=true rows",
    )
    parser.add_argument(
        "--expected-implemented",
        type=int,
        default=45,
        help="Expected count for implementation_state=implemented rows",
    )
    parser.add_argument(
        "--output-dir",
        default=f"audit-results/brazil-coverage-{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}",
        help="Directory for gate reports",
    )
    args = parser.parse_args()

    registry_path = Path(args.registry_path)
    runner_path = Path(args.runner_path)
    output_dir = Path(args.output_dir)

    rows, registry_errors = read_registry(registry_path)
    runner_pipelines, runner_errors = parse_runner_pipelines(runner_path)

    if registry_errors or runner_errors:
        output_dir.mkdir(parents=True, exist_ok=True)
        combined = registry_errors + runner_errors
        (output_dir / "source_completeness_report.md").write_text(
            "# Source Completeness Gate Report\n\n"
            + "\n".join(f"- FAIL: {msg}" for msg in combined)
            + "\n",
            encoding="utf-8",
        )
        print("\n".join(combined))
        return 1

    gates, status_counter, implementation_counter = build_gate_results(
        rows=rows,
        runner_pipelines=runner_pipelines,
        expected_universe=args.expected_universe_v1,
        expected_implemented=args.expected_implemented,
    )
    write_outputs(
        output_dir=output_dir,
        registry_path=registry_path,
        runner_path=runner_path,
        expected_universe=args.expected_universe_v1,
        expected_implemented=args.expected_implemented,
        gates=gates,
        status_counter=status_counter,
        implementation_counter=implementation_counter,
    )

    all_passed = all(gate.passed for gate in gates)
    print("PASS" if all_passed else "FAIL")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
