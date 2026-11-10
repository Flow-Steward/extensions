# Remaining dependency updates — 2026-11-10

Published new versions for all 17 affected extensions. The
[final full-catalog monitor](https://github.com/Flow-Steward/extensions/actions/runs/42873690976)
reports **45 extensions, zero update events, zero security matches and zero
collection errors**. Exact report comparison confirms all original 95 update
and 11 source-advisory events removed, together with two fresh patch notices that
appeared during execution.

The input was the complete [106-signal report](https://github.com/Flow-Steward/extensions/actions/runs/42846402128):
45 extensions, 95 ordinary update events and 11 separately tracked Toolbox source
advisories, with zero collection errors. The 95 updates affect 17 repositories:
15 native connectors plus File Transfer and Vertex. The work preserves existing
extension IDs, host APIs, fixed database profiles and safety controls.

## Reviewed releases

| Repository | Version |
|---|---|
| [ext-ai-google-cloud-vertex](https://github.com/Flow-Steward/ext-ai-google-cloud-vertex/releases/tag/v0.1.4) | 0.1.4 |
| [ext-data-bigquery](https://github.com/Flow-Steward/ext-data-bigquery/releases/tag/v1.1.5) | 1.1.5 |
| [ext-data-clickhouse](https://github.com/Flow-Steward/ext-data-clickhouse/releases/tag/v1.3.4) | 1.3.4 |
| [ext-data-firestore](https://github.com/Flow-Steward/ext-data-firestore/releases/tag/v1.0.5) | 1.0.5 |
| [ext-data-mongodb](https://github.com/Flow-Steward/ext-data-mongodb/releases/tag/v1.1.4) | 1.1.4 |
| [ext-data-mssql](https://github.com/Flow-Steward/ext-data-mssql/releases/tag/v1.3.4) | 1.3.4 |
| [ext-data-mysql](https://github.com/Flow-Steward/ext-data-mysql/releases/tag/v1.3.4) | 1.3.4 |
| [ext-data-oceanbase](https://github.com/Flow-Steward/ext-data-oceanbase/releases/tag/v1.3.4) | 1.3.4 |
| [ext-data-oracle](https://github.com/Flow-Steward/ext-data-oracle/releases/tag/v1.1.4) | 1.1.4 |
| [ext-data-postgres](https://github.com/Flow-Steward/ext-data-postgres/releases/tag/v1.4.4) | 1.4.4 |
| [ext-data-redis](https://github.com/Flow-Steward/ext-data-redis/releases/tag/v1.1.4) | 1.1.4 |
| [ext-data-singlestore](https://github.com/Flow-Steward/ext-data-singlestore/releases/tag/v1.3.5) | 1.3.5 |
| [ext-data-snowflake](https://github.com/Flow-Steward/ext-data-snowflake/releases/tag/v1.3.5) | 1.3.5 |
| [ext-data-spanner](https://github.com/Flow-Steward/ext-data-spanner/releases/tag/v1.3.4) | 1.3.4 |
| [ext-data-valkey](https://github.com/Flow-Steward/ext-data-valkey/releases/tag/v1.1.4) | 1.1.4 |
| [ext-file-transfer-sftp](https://github.com/Flow-Steward/ext-file-transfer-sftp/releases/tag/v0.3.3) | 0.3.3 |
| [ext-graph-neo4j](https://github.com/Flow-Steward/ext-graph-neo4j/releases/tag/v1.0.5) | 1.0.5 |

## Compatibility work

All native connectors move to exact Toolbox 1.16.0 source commit
`06ea49d9a487a72c22419b5a8d5c22c11f0d7485`, official checksum-pinned Go 1.27.4 SDK
and the shared reviewed 106-module floor baseline. Because the 1.27.4 Docker tag
was not yet available, the build uses the immutable official Go 1.27.3 image
`sha256:dc0963f32053e4bc451d24d87e3892d42d01021b61f093e98eb95c0352bb84b0`
solely as a bootstrap environment. A recorded helper verifies the official SDK
archive SHA256 and replaces the compiler before any Go command in the build;
selected SDK URL, architecture and hash are included in provenance. All 30 final
native payloads report Go 1.27.4. Corrupt SDK input is rejected before
compiler replacement. The 1.16 BaseTool, ConfigBase and direct-source APIs required
compatibility ports in the existing tools and drivers.

Bound parameter fidelity, execute-once writes, endpoint/TLS/pinned-address policies,
vector and response bounds, disabled retries, explicit transaction cleanup and
custom Firestore transport limits were preserved. New upstream tools, prompts and
file/text resources are excluded; approved old profiles remain explicit recorded
patches. Startup version-check network requests are disabled. Truthful current
source identities replace old 1.3 identities; all 11 earlier advisory fix commits
are ancestors of 1.16.

A pre-release scan of actual linked modules detected two new transitive notices
introduced by 1.16 (Cloud Go SQL and x/mod); these were updated before delivery.
An upstream same-path Thrift replacement was removed in favor of the official
current module, preserving strict binary replacement gates. Neo4j's disclosed
local socket/wire fork was ported to actual latest driver 6.4.0 with its own pinned
source/patch provenance. Supplemental upstream module monitoring retains the
actual local replacement coverage gap.

Snowflake driver 2.4.0 changed its default OCSP policy. A real parser/connector
regression and exact driver policy controls prove that the source patch explicitly
restores prior fail-open OCSP checking with `ocspFailOpen=true` and preserves the
existing environment opt-out. Both final binaries were checked for the fix.

Vertex now uses official google-auth 2.62.2. A bounded blocking regional access
boundary lookup preserves discovery, headers and regional bypass while completing
all authentication work before disposing the invocation Session. The pinned SDK
hook is private but explicitly documents its gcloud compatibility purpose; future
upgrades must rerun lifecycle controls.

File Transfer now uses official dateutil 4.0.0 / tzdata 2026.6 and reproducible, clearly
identified maintained builds of botocore 1.43.127+flowsteward.1 and
aiobotocore 3.10.0+flowsteward.1. Official upstream constraints cannot resolve these
latest public releases together. Exact official inputs, narrow source/metadata
patches, output hashes and licenses are recorded in the release's
[dependency-sources.json](https://github.com/Flow-Steward/ext-file-transfer-sftp/blob/v0.3.3/dependency-sources.json).
The async presign condition-copy fix is ported; all other upstream wheel contents
were checked against declared patch scope. The project maintains this exact compatibility graph.

The monitor conservatively checks Python local builds against their public
upstream advisory version while retaining the complete installed local version.
An integration regression that hid all File Transfer dependencies was caught
before publication: offline installer flags moved out of declarative requirement
files into installer commands. Unchanged discovery retains 32 distinct PyPI
identities, with no source-identity gaps for that extension.

## Verification

- All 17 candidates received independent source/asset review; no unresolved
  Critical or Important findings. Every final archive is bound to an immutable
  reviewed commit and exact native/module/provenance hashes.
- Initial SQL source suites: 934 tests passed, 319 expected environment/live skips.
  Real PostgreSQL+pgvector: 11 tests on each architecture; MySQL/OceanBase: four
  real MariaDB wire cases. All 10 installed SQL archive gates passed. Fixed 10s
  registration and 50ms transport limits were retained; final serialized runs
  passed after build contention ended.
- ClickHouse/Snowflake/Spanner independent full suites: 187/186/203 passed;
  expected skips 72/74/71. All native source/tool tests and both architecture
  recipes passed, including real Spanner tests and the Snowflake OCSP repair.
- Seven custom connectors: 739 source tests passed, 11 live/environment skips;
  1062 packaged tests passed. All 14 binaries executed, all 14 archives passed
  current catalog acceptance, and 48 unapproved-registration probes passed.
  BigQuery actual Core 1.5 host dispatch passed.
- Vertex: 44 packaged tests passed on each architecture, plus offline hash
  installs, pipcheck and health. File Transfer: 339 full tests / 14 external skips
  and 63 extracted-archive protocol tests on each architecture, 40 upstream
  botocore parser/credential tests, reproducible wheel rebuilds and clean
  offline dependency installation. Both corrected File Transfer archives retain
  monitored local/base dependency identities.
- Complete catalog monitor suite: 300 passed. Actual new native metadata covers
  155 module/version pairs with no comparable stable updates. OSV 158 exact
  module/standard-library/source-commit queries returned zero known matches.
  These are source-limited observations, not a security certification.

The Go 1.27.4 follow-up reran all five SQL source suites: 939 passed and
319 expected skips. The 22 live PostgreSQL/vector checks and all ten installed
SQL archive gates passed again, including actual Go 1.27.3 rejection. Every new
native binary retains the exact prior linked-module map. Vertex 0.1.4 reran its
44 source and 44-per-architecture packaged tests; public release contents match
the reviewed archive members. ClickHouse/Snowflake/Spanner follow-up full suites
passed 188/187/204 tests, with expected skips 72/74/71; independent focused
compiler/native/identity suites passed another 33/32/44 tests. The seven custom
connector follow-up suites passed 743 source tests (11 expected skips; three
unchanged BigQuery compression/host-repacking cases deselected using their prior
proof) and 1,062 fresh packaged tests. All 14 fresh archives passed current catalog
acceptance and both architectures executed their actual new native payloads.
Fresh BigQuery Core admission/dispatch is verified on the available ARM64 host;
no fresh AMD64 Core-host integration claim is made. An attempted cross-target
admission correctly rejected the AMD64 ZIP on the ARM64 host; the platform guard
was preserved. A separate Go 1.27.4 OSV query returned zero known matches.

## Coverage and intentional limits

Authenticated production cloud/provider integration was not exercised. PostgreSQL
and MySQL-protocol local fixtures provide the specific live coverage stated above;
SingleStore-specific live semantics, vectors and authentication remain unverified.
The MariaDB fixture does not implement SingleStore's vendor startup setting;
exploratory proxy results are excluded and product defaults are unchanged.

BigQuery's new optional upstream billing-label feature is not exposed by the
existing Flow Steward host API and was deliberately not added in this maintenance
migration. The existing behavior remains. Neo4j's actual `/driver (devel)` runtime
replacement gap remains visible despite supplemental source-identity lookups.
Pseudo-version ordering, unpinned development dependencies, the nonpublic SDK and
external SaaS API changes remain documented monitor coverage limits.

## Final catalog and report

The first publication was indexed in catalog revision `2026-11-10.34631f80`.
The [complete main-branch run](https://github.com/Flow-Steward/extensions/actions/runs/42863748602)
checked all 45 extensions, with zero collection errors. Exact report-key comparison
shows all original 95 update events and all 11 Toolbox source advisory events
removed. The report artifact SHA256 is
`4c4cb3be71bdcd625ecded15424415e567afa2855b0da062a4dc2b4d6439bc92`.

That run found two newly published updates: google-auth 2.62.2 and Go 1.27.4.
Both are included in a follow-up patch pass under new tags.
This adds 16 new releases to the original 17 releases, across the same 17
extensions. All 30 native public ZIP digests and 15 checksum files match their
independently reviewed bytes. Both Vertex public ZIPs match reviewed member
contents; its workflow rebuild changes ZIP timestamps and therefore archive digests.

[Final catalog publication](https://github.com/Flow-Steward/extensions/actions/runs/42873310270)
succeeded: revision `2026-11-10.2c1da96c`, commit
`73370bb2e6a2b7eb62fc81a38f53fdbd07cefea5`. All 17 versions and 34 target
hashes/sizes match the public releases. The full catalog suite was rerun on this
refreshed tree: 300 passed. Final monitor
[42873690976](https://github.com/Flow-Steward/extensions/actions/runs/42873690976)
succeeded in 3m 29s on that exact main-branch commit. It checked at
`2026-11-10T18:17:41.023200+00:00`. Its exact report artifact SHA256 is
`cc79ca3eb700d3504754c4772befe125d81aa847fb26122f7878bf313837c970`.

| Complete run | Extensions | Updates | Security signals | Errors |
|---|---:|---:|---:|---:|
| [Input #4](https://github.com/Flow-Steward/extensions/actions/runs/42846402128) | 45 | 95 | 11 | 0 |
| [Initial publication #5](https://github.com/Flow-Steward/extensions/actions/runs/42863748602) | 45 | 2 | 0 | 0 |
| [Final patch publication #6](https://github.com/Flow-Steward/extensions/actions/runs/42873690976) | 45 | 0 | 0 | 0 |

The downloaded final artifact matches GitHub's displayed digest. Exact-key
comparison removes all 106 original events and both intermediate notices.
A separate inventory comparison confirms the same monitored dependency identities
and scopes for all 17 extensions, with only the expected compiler/auth version
changes in the patch pass. All 30 native runtime targets report Go 1.27.4;
both Vertex runtime targets report google-auth 2.62.2; File Transfer's maintained
AWS identities remain visible; Neo4j's actual local-driver coverage gap remains
reported. The zero result therefore retains the previous inventory and coverage
limits. This dry-run report does not automatically close existing GitHub issues.
