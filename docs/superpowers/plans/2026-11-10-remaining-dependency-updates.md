# Remaining Dependency Updates Implementation Plan

> **For agentic workers:** Use the established parallel repository groups; implement each compatibility fix with a failing behavioral regression, and obtain fresh review before release.

**Goal:** Resolve all 95 ordinary update events from monitor run 42846402128 through dependency upgrades, compatibility repairs and published releases.

**Architecture:** Keep the existing extension IDs and host APIs. Upgrade the shared Toolbox source/toolchain/module baseline once, then port each database's existing safety patches and limited registrations. Independently repair the two Python repositories. Root integrates, publishes and compares exact report keys.

**Tech Stack:** Python 3.12, Go, pinned official Docker images, offline hashed wheels, GitHub releases and the catalog monitor.

**Spec:** The user's instruction in this chat: update dependencies in order, test compatibility, fix incompatibilities, release new versions. Previous security batch constraints and evidence: `docs/extension-maintenance-2026-11-10.md`.

## Global Constraints

- Baseline: 45 extensions, 95 update events plus 11 separately tracked source advisories, zero collection errors.
- User explicitly authorizes implementation and publication; continue without another design/permission handoff.
- Preserve extension IDs, host protocol, fixed stdio launch, bounded parameter binding, vector/SQL restrictions, endpoint/TLS checks, resource limits, local Neo4j socket controls and disabled retries.
- Use task-owned clones/branches; preserve the prior batch and all user files. No broad Docker cleanup; cap concurrent Go builds at three.
- Use current official releases and exact source/image/module identities. Never falsify upstream versions or remove constraints merely to make a resolver pass.
- Both Linux AMD64 and ARM64 release assets must pass catalog acceptance, actual module/provenance checks and packaged compatibility tests. No live-auth claim without credentials.
- Report every unresolved event with evidence; do not suppress update notices to manufacture zero.

## Review Focus

- New upstream CLI/profile registrations must not expose unrestricted tools or transports.
- Source safety patches must still execute in the new driver's actual call path.
- Async authentication/session work must finish or be cancelled before transport disposal.
- AWS dependency compatibility must be demonstrated with real metadata, install checks and client behavior, not a forced resolver.
- Actual released binary modules and offline installed wheels must match the recorded dependency versions and hashes.

## Tasks

- [x] 1. Freeze the 95-event inventory and map every event to affected repositories and intended target versions. Verify current upstream metadata.
- [ ] 2. Vertex: reproduce google-auth 2.62.1 lifecycle failure with the existing real-credential control, repair ownership/lifecycle, update hashed wheels and tests, prepare next patch release.
- [ ] 3. File Transfer: resolve botocore 1.43.127 / python-dateutil 4.0.0 incompatibilities through a supported dependency graph or a narrowly justified, truthful compatibility adaptation; preserve S3/FTP/SFTP/Dropbox behavior and offline install integrity. Prepare next patch release only after resolver and behavioral gates.
- [ ] 4. Toolbox migration: compare exact v1.16.0 source to v1.3.0, port the shared baseline to Go 1.27.3 and all 90 Go module update targets and the toolchain. Reproduce and repair compiler/API breaks; retain explicit upstream identities.
- [ ] 5. Port and test five SQL connectors (PostgreSQL, MySQL, MSSQL, OceanBase, SingleStore) against the shared new baseline; build both architectures and prepare next patch versions.
- [ ] 6. Port and test ClickHouse, Snowflake and Spanner, retaining actual binding/compression/source checks; build both architectures and prepare next patch versions.
- [ ] 7. Port and test BigQuery, Firestore, MongoDB, Neo4j, Oracle, Redis and Valkey, preserving bespoke mains/driver forks/limits; build both architectures and prepare next patch versions.
- [ ] 8. Obtain fresh independent review of final candidate source and assets; fix substantive findings with RED/GREEN behavior controls and the relevant full suite.
- [ ] 9. Publish reviewed commits/tags/assets; verify public payload digests/content, refresh catalog, run a complete dry-run monitor, and compare baseline keys. Record final releases, tests, coverage and any remaining incompatible upstream constraints.

## Execution Ledger

- Existing catalog worktree is isolated on `codex/extensions-security-batch`, clean at intake. Prior release clones are task-owned under `/private/tmp/fs-security-batch-20261110`; new scratch evidence belongs under `/private/tmp/fs-updates-95-20261110`.
- Independent work domains: Vertex, File Transfer, shared native migration investigation. Database implementation groups wait for the shared source/module baseline; they must not invent independent baselines.


### Current checkpoints

- Frozen event inventory: `/private/tmp/fs-updates-95-20261110/baseline-updates.json`.
  17 repositories: 15 native connectors, File Transfer and Vertex. Categories:
  90 Go module updates, Go compiler, Toolbox upstream and three Python updates.
- Official source v1.16.0 is commit06ea49d9a487a72c22419b5a8d5c22c11f0d7485.
  Official Go image1.27.3-bookworm digestdc0963f32053e4bc451d24d87e3892d42d01021b61f093e98eb95c0352bb84b0.
- Source investigator completed matrix, exact upstream advisory fix ancestry and
  frozen profile patch. All 11 previous source-advisory fixes are ancestors of
  v1.16.0. Root still requires actual final OSV queries and complete monitor.
- Profile compatibility patch SHA256df264c60006ad1a01812b427fb6a9593115ddd86227fc9522b8bae6731616aca.
  It restores exact approved1.3 YAML profiles before registration discovery;
  otherwise1.16 introduces unrequested database tools. Remove unused new prompt
  and file/text resource registrations, disable startup version-check network IO.
- First shared graph resolved103 exact update/security-floor targets. A v2 graph
  is being frozen separately: remove upstream's redundant same-path Thrift
  replacement and require the official current module, preserving strict native
  replacement gates. v1 artifacts remain frozen; do not build final assets yet.
- Vertex committed d3ddf21ac0103d68962fc022cbef03c5a55a77e9, version0.1.3:
  google-auth2.62.1; bounded blocking RAB lookup preserves auth behavior. Real
  baseline regression8failed/1pass; candidate source44passed, packaged44passed
  each arch; offline hash installs/pipcheck/health/catalog acceptance passed.
  Await fresh review before publication.
- AWS official graph cannot combine latest botocore/dateutil/aiobotocore. Worker
  implements small explicit local forks from exact official wheels, reproducible
  patches+provenance, real presign/parser/TLS client behavior and clean pipcheck.
  Runtime names stay unchanged; full local versions remain visible.
- Catalog monitor local Python builds now query their public upstream version
  conservatively (no advisory suppression). RED/GREEN includes ordinary and
  +incompatible local suffixes; complete catalog suite290passed.
- Active workers (do not redispatch after compaction): vertex_latest_compat done;
  aws_latest_compat; sql_latest_migration (five SQL+shared tools binding patch);
  special_latest_migration (three special+source write once-only ports);
  nosql_latest_migration (seven custom, owns narrow Neo4j source-only subagent).
- Scratch migration report: /private/tmp/fs-updates-95-20261110/investigation/toolbox-migration-map.md.
  Root artifacts under /private/tmp/fs-updates-95-20261110. Existing task-owned
  release clones reused on codex/remaining-updates-20261110 branches. Root catalog
  branch codex/remaining-dependency-updates. No new publication yet.


### Frozen v2 baseline and first review

- All three native groups received final **v2** artifacts and may build one
  native job per group. Module patch `/private/tmp/fs-updates-95-20261110/latest-dependencies-v2.patch`
  SHA256af406af0a861bea0b8e3d83e55fbdef9173cc01762788c6d06cc9b47eaa558e1.
  104 exact module targets, Go1.27.3. go.mod1c59a76307271df0a6992d9db406f9c49ba670dfb898e029bbc86136adcc9294;
  go.sumd0e98fac8a9d4677bc239a668b472dd2f459ab65f3d0fec7ceb2a50bb6138841.
  `native-latest-baseline-v2.json` and `baseline-identities-v2.json` are authoritative.
- Ruling: remove upstream's same-path Apache Thrift replacement, require official
  latestv0.25.0 directly — avoids weakening payload replacement checks. The only
  retained source replacement is Cassandra, excluded by all shipped profiles.
- Shared full SQL/write binding patch `sql/shared-binding-v1.patch` SHA256
  b3c627eb605947134461c6a47dee83341c57e94508e4f9199df613937adf9eb8;
  PostgreSQLvector separate `sql/managed-vector-v1.patch` SHA256
  b73bf682eea7f7365c4a2be88fcab9f19ed75a91b4ac42318ddb05a226cf5eea.
  Meaningful native RED/GREEN covers Invoke→RunSQL actual values, Invoke→RunWrite
  dispatch and strict endpoint/wire/timeout protections. Final recipes still running.
- Vertex final both-arch packaged suites44passed each, no-network hash installs,
  pipcheck and health passed. Source remains frozen d3ddf21a.
- Fresh reviewer `review_vertex_and_monitor_latest` reviewing Vertex and root
  monitor2037c81 independently. No source/tag/release pushes yet.
- AWS arm64 final package gate339passed/14optional live skips; amd64 gate pending.
  Worker adding mandatory source/patch/wheel provenance negative controls. These
  own fork versions expose original public identities to conservative OSV checks.


- Fresh review approved Vertexd3ddf21 and monitor2037c81 with no findings.
  Independent Vertex archive44passed; independent whole catalog suite290passed.
  Live IAM behavior remains outside credential-free verification; future SDK
  upgrades must rerun lifecycle controls. OSV completeness is an external limit.
  Historical local SHA256SUMS is not used for current publication.
- Exact v2 baseline OSV105queries returned zero known non-withdrawn matches.
  Evidence /private/tmp/fs-updates-95-20261110/baseline-v2-osv.json.
- AWS both architectures offline complete suite339passed/14optional integration
  skips; final extracted-archive protocol tests and immutable commit still pending.
