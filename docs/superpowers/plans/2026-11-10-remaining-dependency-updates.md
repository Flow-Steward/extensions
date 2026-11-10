# Remaining Dependency Updates — Completed Execution Plan

**Goal:** Resolve the 95 ordinary update events from complete monitor run
42846402128 through actual upgrades, compatibility repairs, tests and public releases.

**Scope:** 17 extensions: 15 native database connectors, File Transfer and Vertex.
Keep extension IDs, host APIs, approved profiles and existing safety controls.
The user authorized implementation and publication in this chat. Existing task-owned
clones and the isolated catalog worktree were reused; user files and unrelated
containers were preserved.

## Completed work

- [x] Freeze the complete 45-extension input: 95 updates, 11 source advisories,
  zero collection errors. Compare exact finding keys after publication.
- [x] Migrate Toolbox to exact 1.16.0 source and the reviewed 106-module baseline;
  port BaseTool, ConfigBase and direct-source API compatibility.
- [x] Preserve parameter binding, execute-once writes, approved registrations,
  vector/response bounds, transport/TLS/pinned-address controls and disabled retries.
- [x] Repair Snowflake's changed OCSP default, Vertex's credential/session lifecycle,
  concrete MongoDB Source contracts and the Neo4j 6.4 socket/wire fork.
- [x] Maintain explicit reproducible AWS compatibility builds from exact official
  wheels; retain local versions, patch/input/output hashes and license provenance.
- [x] Preserve monitor coverage for Python local versions and source-declared Go
  forks while retaining actual runtime gaps. Complete catalog suite: 300 passed.
- [x] Build both Linux architectures and run relevant source, native, packaged,
  local database and current-catalog checks; obtain independent source/asset review.
- [x] Publish the original 17 releases and verify all 34 public target archives.
- [x] Detect two newly published patches in the intermediate complete monitor:
  google-auth 2.62.2 and Go 1.27.4. Include both in 16 follow-up patch releases.
- [x] Install the official checksum-pinned Go 1.27.4 SDK before any build Go command
  using the immutable official image as bootstrap. Bind installer/source/selected
  SDK provenance. Actual old-compiler rejection and corrupt-SDK rejection controls pass.
- [x] Rebuild all 30 native payloads; preserve exact linked module maps and source
  patches. Rerun fixed-deadline suites serially after all native builders finish.
- [x] Independently approve the 16 follow-up candidates. Verify all 30 public native
  archive digests and 15 checksum files; verify Vertex public archive member contents.
- [x] Publish and verify final catalog: all 17 versions, 34 target hashes/sizes,
  45 total extensions. Rerun the complete catalog suite on the refreshed tree: 300 passed.
- [x] Complete final full monitor, download its exact artifact and compare keys and
  dependency inventories. Result: 45 extensions, zero findings, zero errors.
- [x] Record releases, compatibility decisions, tests and coverage limits in the
  [final maintenance report](../../extension-updates-2026-11-10.md).

## Immutable final verification

- [Catalog publication](https://github.com/Flow-Steward/extensions/actions/runs/42873310270):
  revision `2026-11-10.2c1da96c`, commit `73370bb2e6a2b7eb62fc81a38f53fdbd07cefea5`.
- [Final full monitor](https://github.com/Flow-Steward/extensions/actions/runs/42873690976):
  checked `2026-11-10T18:17:41.023200+00:00`, successful in 3m 29s.
- Report artifact SHA256:
  `cc79ca3eb700d3504754c4772befe125d81aa847fb26122f7878bf313837c970`.
- All 106 original keys and both intermediate fresh-update keys are absent.
  Dependency inventory comparison preserves monitored identities/scopes and verifies
  all native runtime compilers and both Vertex auth wheels at the new versions.
- Detailed task evidence: `/private/tmp/fs-updates-95-20261110`; final patch manifests,
  independent reviews, public-byte checks and inventory comparison under `final-patches`.

## Explicit limits

No authenticated production cloud-service compatibility claim is made. Local
PostgreSQL/pgvector and MySQL-protocol coverage is documented in the report;
SingleStore-specific live behavior remains unverified. Fresh BigQuery Core-host
admission/dispatch is ARM64 only; both targets pass native, package and catalog gates.
Unchanged heavy BigQuery source proofs were reused without duplicate compression.
Neo4j's actual local-driver replacement gap and other monitor coverage limits remain
visible. Optional new BigQuery billing labels were outside this maintenance scope.
All task-owned build/test resources are idle; the host-managed worktree is preserved.
