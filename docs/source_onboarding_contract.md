# Source Onboarding Contract (Brazil Coverage v1)

This contract is mandatory for every new source before `shadow -> promote`.

## 1. Source Identity
- `source_id`:
- `name`:
- `category`:
- `tier`:
- `owner_agent`:
- `primary_url`:
- `access_mode` (`file|api|bigquery|web`):
- `public_access_mode` (`open|open_with_rate_limit|registration|credentialed_public`):
- `discovery_status` (`discovered|discovered_uningested|monitored|unreachable`):
- `last_seen_url`:
- `cadence_expected`:
- `cadence_observed`:
- `quality_status` (`healthy|stale|quality_fail|blocked_external|not_built|partial|loaded`):

## 2. Access and Legal
- Credential required:
- Secret name/path:
- License or usage restriction:
- LGPD/privacy considerations:
- `blocked_external` criteria:

## 3. Data Contract
- Downloader script: `etl/scripts/download_<source>.py`
- Canonical output files:
- Manifest file:
- Manifest mandatory fields (`run_id`, `source_id`, `window_start`, `window_end`, `rows`, `error`, `checksum`, `retrieved_at_utc`):
- Update cadence:
- Expected row volume:
- Partition/window strategy:

## 4. Graph Contract
- Node labels introduced:
- Relationship types introduced:
- Natural key(s) per node:
- Merge key strategy:
- Relationship quality tier (`strong|probable`):
- Provenance fields (`method`, `confidence`, `source_ref`, `run_id`):

## 5. Index and Constraint Contract
- Required uniqueness constraints:
- Required date indexes:
- Required lookup indexes:
- Required fulltext indexes (if text-heavy):

## 6. Quality Gates (Hard Stop/Go)
- Identity integrity preserved (`Person.cpf` masked = 0, 14-digit = 0):
- Freshness SLA threshold:
- Temporal sanity (`<= now + 365d`):
- Null/duplicate key thresholds:
- Mandatory non-zero nodes/rels:

## 7. Operational Flow
- Shadow load command:
- Gate runner commands:
- API smoke checks:
- Promote command:
- Rollback command:

## 8. Acceptance
- Evidence bundle path in `audit-results/`:
- Final status: `resolved | resolved_full | blocked_external | quality_fail`
- Reviewer sign-off:
