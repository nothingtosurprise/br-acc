#!/usr/bin/env python3
"""Discover public data sources and produce registry delta artifacts.

This script is non-destructive by default: it never rewrites the canonical registry.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

URL_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
SITEMAP_LOC_RE = re.compile(r"<loc>([^<]+)</loc>", re.IGNORECASE)
RSS_LINK_RE = re.compile(r"<link>([^<]+)</link>", re.IGNORECASE)

DISCOVERY_SEEDS = (
    "https://dados.gov.br/dados/conjuntos-dados",
    "https://www12.senado.leg.br/dados-abertos",
    "https://dadosabertos.camara.leg.br/swagger/api.html",
    "https://www.cnj.jus.br/sistemas/datajud/",
    "https://api-publica.datajud.cnj.jus.br/",
    "https://www.tesourotransparente.gov.br/",
    "https://www.transferegov.sistema.gov.br/portal/download-de-dados",
    "https://queridodiario.ok.org.br/api",
    "https://basedosdados.org/dataset",
)

SIGNAL_KEYWORDS = (
    "dados",
    "dataset",
    "download",
    "api",
    "transparencia",
    "dados-abertos",
    "open-data",
    "csv",
    "json",
    "xml",
    "parquet",
    "sitemap",
    "rss",
)


@dataclass(frozen=True)
class RegistryRow:
    source_id: str
    primary_url: str
    last_seen_url: str


def _canonicalize(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        return ""
    clean = parsed._replace(fragment="")
    text = clean.geturl()
    return text[:-1] if text.endswith("/") else text


def _read_registry(path: Path) -> list[RegistryRow]:
    rows: list[RegistryRow] = []
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(
                RegistryRow(
                    source_id=(row.get("source_id") or "").strip(),
                    primary_url=(row.get("primary_url") or "").strip(),
                    last_seen_url=(row.get("last_seen_url") or "").strip(),
                )
            )
    return rows


def _snapshot_path(output_dir: Path, url: str, content_type: str) -> Path:
    suffix = ".txt"
    lowered = content_type.lower()
    if "html" in lowered:
        suffix = ".html"
    elif "xml" in lowered:
        suffix = ".xml"
    elif "json" in lowered:
        suffix = ".json"
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return output_dir / "snapshots" / f"{key}{suffix}"


def _extract_links(url: str, body: str, content_type: str) -> set[str]:
    links: set[str] = set()
    lowered = content_type.lower()
    patterns = [URL_RE]
    if "xml" in lowered:
        patterns.extend([SITEMAP_LOC_RE, RSS_LINK_RE])
    for pattern in patterns:
        for match in pattern.findall(body):
            joined = urljoin(url, html.unescape(match))
            clean = _canonicalize(joined)
            if not clean:
                continue
            if any(keyword in clean.lower() for keyword in SIGNAL_KEYWORDS):
                links.add(clean)
    return links


def _fetch_all(
    seeds: list[str],
    output_dir: Path,
    max_pages: int,
    timeout_seconds: float,
) -> tuple[dict[str, str], dict[str, str], set[str]]:
    queue: list[str] = [_canonicalize(seed) for seed in seeds if _canonicalize(seed)]
    seen: set[str] = set()
    discovered: set[str] = set(queue)
    content_map: dict[str, str] = {}
    error_map: dict[str, str] = {}

    output_snapshots = output_dir / "snapshots"
    output_snapshots.mkdir(parents=True, exist_ok=True)

    with httpx.Client(follow_redirects=True, timeout=timeout_seconds) as client:
        while queue and len(seen) < max_pages:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            try:
                response = client.get(current)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "text/plain")
                text = response.text
                content_map[current] = content_type

                snap = _snapshot_path(output_dir, current, content_type)
                snap.write_text(text, encoding="utf-8")

                for link in _extract_links(current, text, content_type):
                    if link not in discovered:
                        discovered.add(link)
                    if link not in seen and len(seen) + len(queue) < max_pages:
                        queue.append(link)
            except Exception as exc:  # noqa: BLE001
                error_map[current] = str(exc)

    return content_map, error_map, discovered


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry-path",
        default="docs/source_registry_br_v1.csv",
        help="Path to source registry CSV.",
    )
    parser.add_argument(
        "--output-dir",
        default=f"audit-results/discovery-{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}",
        help="Output directory for discovery artifacts.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=250,
        help="Max pages to crawl per run.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds.",
    )
    args = parser.parse_args()

    registry_path = Path(args.registry_path)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = _read_registry(registry_path)
    known_urls: set[str] = set()
    for row in rows:
        primary = _canonicalize(row.primary_url)
        last_seen = _canonicalize(row.last_seen_url)
        if primary:
            known_urls.add(primary)
        if last_seen:
            known_urls.add(last_seen)

    seed_urls = list(DISCOVERY_SEEDS)
    seed_urls.extend([row.primary_url for row in rows if row.primary_url])

    content_map, error_map, discovered = _fetch_all(
        seeds=seed_urls,
        output_dir=output_dir,
        max_pages=args.max_pages,
        timeout_seconds=args.timeout_seconds,
    )

    discovered_only = sorted(url for url in discovered if url not in known_urls)
    known_discovered = sorted(url for url in discovered if url in known_urls)

    _write_csv(
        output_dir / "discovered_urls.csv",
        [
            {
                "url": url,
                "is_known": "true" if url in known_urls else "false",
                "content_type": content_map.get(url, ""),
                "error": error_map.get(url, ""),
            }
            for url in sorted(discovered)
        ],
    )
    _write_csv(
        output_dir / "discovered_uningested_candidates.csv",
        [{"url": url} for url in discovered_only],
    )

    summary = {
        "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "registry_path": str(registry_path),
        "known_url_count": len(known_urls),
        "discovered_url_count": len(discovered),
        "known_discovered_count": len(known_discovered),
        "discovered_uningested_count": len(discovered_only),
        "errors_count": len(error_map),
        "max_pages": args.max_pages,
    }
    (output_dir / "discovery_summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Discovery Summary",
        "",
        f"- timestamp_utc: `{summary['timestamp_utc']}`",
        f"- known_url_count: `{summary['known_url_count']}`",
        f"- discovered_url_count: `{summary['discovered_url_count']}`",
        f"- discovered_uningested_count: `{summary['discovered_uningested_count']}`",
        f"- errors_count: `{summary['errors_count']}`",
        "",
        "## Files",
        "",
        "- `discovered_urls.csv`",
        "- `discovered_uningested_candidates.csv`",
        "- `discovery_summary.json`",
        "- `snapshots/`",
    ]
    (output_dir / "discovery_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
