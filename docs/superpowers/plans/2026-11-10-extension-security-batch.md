# Extension security batch implementation plan

Goal: repair and release every affected extension from the successful 219-signal
monitor report, beginning with shared database native dependencies; verify remaining
signals rather than assuming a dependency update proves compatibility.

User scope: proceed through all affected extensions, fix, test and publish; no
additional design/permission checkpoint is needed for this already authorized work.

Global constraints: preserve host extension IDs/APIs, fixed stdio invocation,
SQL parameter binding, resource limits, database-specific safety patches and archive
checks. Do not claim live service integration without credentials. Preserve local
user changes by using disposable per-repository clones. Never execute downloaded
untrusted binaries. The existing catalog workspace is already an isolated worktree.

- [x] Intake exact report: run 42828802606, 219 findings (90 security/129 update),
  45 extensions, zero errors. 202 findings are exclusive to 15 DB connectors.
- [x] Independently investigate shared boundary and compatibility before edits.
- [x] Prepare one pinned Go module security baseline against exact Toolbox v1.3.0
  b0010060a939455d91e4f8ba62dc3e72b1892469 and official Go 1.26.10 image
  sha256:5de7c99eb78ca5e515a4c340235d0955ec5964a5071c492c15503d7c267da473.
  Add a dependency-floor regression, observe RED on old payload, then GREEN on
  rebuilt metadata. Query the resulting exact modules with OSV.
- [x] SQL variants (postgres, mysql, oceanbase, singlestore, mssql): apply baseline,
  preserve existing native patches, bump patch versions, rebuild both targets,
  run native bound-query regressions + extension compatibility suites, validate ZIPs.
- [x] Specialized SQL/cloud (clickhouse, snowflake, spanner): same gates, preserving
  Snowflake driver >=2.2.0, compression and identity compatibility.
- [x] Native non-SQL variants (bigquery, firestore, mongodb, neo4j, oracle, redis,
  valkey): same baseline/gates, preserve custom mains/driver forks/safety controls.
- [x] Other affected Python extensions: file-transfer, typesafe-ai, example-showcase,
  google-cloud-vertex and Image Processing; update compatible affected pins/wheels,
  retain legitimate behavior, rebuild both targets where applicable and validate.
- [x] Fresh independent bypass/regression review before publishing each group.
- [x] Publish tested release assets, verify catalog versions and hashes, run full
  read-only monitoring, compare baseline keys, explain retained/unreachable signals.

Review focus: only actual shipped modules; per-architecture provenance; readonly
module checks; no accidental SQL/endpoint/redirect safety regression; unchanged
Python host protocol and optional dependency behavior; max 50 MiB release archive.

Execution: fix-finding owns the security gates. Independent repositories may be
handled in parallel under dispatching-parallel-agents; root integrates and publishes.

## Reproducible security baseline

- Exact Toolbox source: v1.3.0, b0010060a939455d91e4f8ba62dc3e72b1892469.
- Official Go image: golang:1.26.10-bookworm@sha256:5de7c99eb78ca5e515a4c340235d0955ec5964a5071c492c15503d7c267da473.
- Shared module patch SHA-256: a6623600324d2bdec1b30102e749678d4fea326bbb9d9f4f586a7ba472d395e2.
- Patched go.mod SHA-256: 7f367f79f68cc28cfcb8c7d36c5533ef79f5016aaeba4443a795a46132105fb5.
- Patched go.sum SHA-256: ca2ace78373b79e7c2b048e69ef22abfb93f1b3a537b7f035ad7c1a0c28542e9.
- Packaging checks actual compiler identity (exact reviewed branch), linked module
  floors, replacement identities and matching provenance. RED/GREEN controls
  include old payloads, stale/forked modules and vulnerable Go 1.27.0/1.27.1.
- All database-specific native safety patches and fixed stdio contracts retained.
- Each repository owns the build recipe, tests and per-target provenance. See the
  [release report](../../extension-maintenance-2026-11-10.md) for all immutable tags.

## Final release checkpoint

All 20 source changes were independently reviewed, merged to their respective main
branches, tagged, and released. All worker build containers are finished.

- All 30 database archives passed the current catalog validator and actual native
  module inventory. OSV returned zero matches for 154 unique component/version
  pairs, including the compiler standard library and preserved Neo4j upstream
  identity. This does not assert the absence of undisclosed vulnerabilities.
- All 15 public database releases were independently checked against the tested
  archives: GitHub asset SHA-256 digests and sizes match exactly; SHA256SUMS matches.
- All eight public Python release archives have the same member bytes as the
  tested local archives; GitHub digests were also verified. Native AMD64 CI passed
  for Showcase, Image, SFTP and Vertex; Typesafe's 38 tests passed both targets.
- Final independent reviewers approved all database groups, including actual
  archives/provenance. PostgreSQL's unchanged strict timeout suite passed after
  builds stopped; no thresholds were relaxed. Spanner's full relevant source
  package ran real tests, replacing an inherited selector that matched none.
- Exact compiler gate rejects stale compiler branches and verifies linked module
  floors plus matching provenance at packaging; old hash-consistent payloads fail.
- BigQuery accurately requires host contract 1.5.0; its actual Core dispatch passed.
- Authenticated live database integration was not exercised.
- Catalog refresh: https://github.com/Flow-Steward/extensions/actions/runs/42845987195
- Catalog commit 86a52d240a5eb43d4982bed035ae615dbde1a88c, revision
  2026-11-10.c6a2d870: all 20 versions and 30 native hashes/sizes match.
- Final monitor https://github.com/Flow-Steward/extensions/actions/runs/42846402128
  succeeded: 45 extensions, 106 findings (11 security/95 ordinary updates), 0 errors.
  Exact keys: 113 resolved, 106 retained, 0 new. All 79 Go/PyPI security findings
  disappeared; 11 upstream source advisories remain with static applicability
  documented in the release report. Existing coverage gaps remain explicit.
- Own temporary audit anchor container removed; no user containers modified.
