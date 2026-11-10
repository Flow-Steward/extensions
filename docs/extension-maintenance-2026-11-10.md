# Extension maintenance releases — 2026-11-10

This batch addresses every extension affected in the 219-signal baseline: 15
native database connectors and five Python extensions. The baseline covered all
45 catalog extensions with no collection errors: 90 security findings and 129
ordinary update notices. Database connectors accounted for 202 signals (89
security, 113 updates).

## Published releases

| Repository | Version |
|---|---|
| [ext-ai-google-cloud-vertex](https://github.com/Flow-Steward/ext-ai-google-cloud-vertex/releases/tag/v0.1.2) | 0.1.2 |
| [ext-data-bigquery](https://github.com/Flow-Steward/ext-data-bigquery/releases/tag/v1.1.3) | 1.1.3 |
| [ext-data-clickhouse](https://github.com/Flow-Steward/ext-data-clickhouse/releases/tag/v1.3.2) | 1.3.2 |
| [ext-data-firestore](https://github.com/Flow-Steward/ext-data-firestore/releases/tag/v1.0.3) | 1.0.3 |
| [ext-data-mongodb](https://github.com/Flow-Steward/ext-data-mongodb/releases/tag/v1.1.2) | 1.1.2 |
| [ext-data-mssql](https://github.com/Flow-Steward/ext-data-mssql/releases/tag/v1.3.2) | 1.3.2 |
| [ext-data-mysql](https://github.com/Flow-Steward/ext-data-mysql/releases/tag/v1.3.2) | 1.3.2 |
| [ext-data-oceanbase](https://github.com/Flow-Steward/ext-data-oceanbase/releases/tag/v1.3.2) | 1.3.2 |
| [ext-data-oracle](https://github.com/Flow-Steward/ext-data-oracle/releases/tag/v1.1.2) | 1.1.2 |
| [ext-data-postgres](https://github.com/Flow-Steward/ext-data-postgres/releases/tag/v1.4.2) | 1.4.2 |
| [ext-data-redis](https://github.com/Flow-Steward/ext-data-redis/releases/tag/v1.1.2) | 1.1.2 |
| [ext-data-singlestore](https://github.com/Flow-Steward/ext-data-singlestore/releases/tag/v1.3.3) | 1.3.3 |
| [ext-data-snowflake](https://github.com/Flow-Steward/ext-data-snowflake/releases/tag/v1.3.3) | 1.3.3 |
| [ext-data-spanner](https://github.com/Flow-Steward/ext-data-spanner/releases/tag/v1.3.2) | 1.3.2 |
| [ext-data-valkey](https://github.com/Flow-Steward/ext-data-valkey/releases/tag/v1.1.2) | 1.1.2 |
| [ext-example-showcase](https://github.com/Flow-Steward/ext-example-showcase/releases/tag/v1.2.3) | 1.2.3 |
| [ext-file-transfer-sftp](https://github.com/Flow-Steward/ext-file-transfer-sftp/releases/tag/v0.3.2) | 0.3.2 |
| [ext-graph-neo4j](https://github.com/Flow-Steward/ext-graph-neo4j/releases/tag/v1.0.3) | 1.0.3 |
| [ext-image-processing](https://github.com/Flow-Steward/ext-image-processing/releases/tag/v0.2.3) | 0.2.3 |
| [ext-typesafe-ai](https://github.com/Flow-Steward/ext-typesafe-ai/releases/tag/v1.0.5) | 1.0.5 |

## Verification and compatibility

Database releases contain Linux AMD64 and ARM64 binaries built with pinned Go
1.26.10 against the exact existing Toolbox 1.3.0 source, with a recorded dependency
patch. Existing SQL binding, vector, resource-limit, endpoint, TLS, retry and
custom-driver controls were preserved. The packaging step now verifies actual
binary compiler/module floors and provenance, rejecting stale but hash-consistent
payloads. All 30 archives passed catalog acceptance and fresh independent review.

Exact OSV queries for 154 unique linked component/version pairs returned no known
matches at verification time. Public release asset sizes and SHA-256 digests match
the tested database archives exactly. The eight published Python archives match
the tested archive member contents; native AMD64 CI and ARM64 suites passed.
Image Processing also passed real model inference. The pytest security regression
covers unsafe symlink target permission mutation and a legitimate control.

BigQuery's minimum host contract is now accurately declared as **1.5.0**, matching
its existing artifact-free service requirement. Actual Core dispatch passed.
Authenticated live database connections were not tested.

Three Python dependency upgrades were deliberately constrained after compatibility
checks: botocore 1.43.117 satisfies aiobotocore 3.10.0's upper bound;
python-dateutil stays on 2.9.0.post0 because the consumer requires <3;
google-auth stays on 2.54.0 because the newer background IAM request can outlive
the shared session. A real service-account lifecycle regression records that last
incompatibility. These are maintenance notices, not a claim that all latest
versions are interchangeable.

Toolbox keeps its truthful upstream source identity. Source-level advisory matches
for HTTP/OAuth and generic tools excluded by these fixed stdio database profiles
are not suppressed by relabeling the source version. These require applicability
context when interpreting the remaining monitor notices.

## Retained Toolbox source advisory applicability

The boundary investigation reviewed these 11 advisory groups against the fixed
stdio launch and registered database tools, rather than assuming every upstream
feature is shipped or reachable:

| Advisory groups | Applicability evidence |
|---|---|
| CVE-2026-11717, CVE-2026-11718 | HTTP/OAuth request-header authentication path; fixed stdio invocation does not expose it. |
| CVE-2026-11719, CVE-2026-14537 | HTTP protocol and legacy authentication paths are not used by the stdio database profiles. |
| CVE-2026-14539 | HTTP buffer/route path is outside the stdio profile. |
| CVE-2026-14540 | Generic HTTP source/tool is excluded from the fixed registrations. |
| CVE-2026-16481 | FHIR source/tool is excluded. |
| CVE-2026-93328, CVE-2026-102242 | Cloud Storage sources/tools are excluded. |
| CVE-2026-15829 | BigQuery forecast tool is excluded. |
| CVE-2026-14538 | Generic BigQuery execute-SQL tool is excluded; the bespoke compiler keeps the stricter existing controls. |

These are static applicability conclusions for the released profiles. Reassess if
transport, source registrations, or launch arguments change. The monitor continues
to report the truthful upstream source matches; no blanket advisory suppression
was added.

## Final monitor comparison

The [catalog publication](https://github.com/Flow-Steward/extensions/actions/runs/42845987195)
succeeded and produced catalog commit `86a52d240a5eb43d4982bed035ae615dbde1a88c`,
revision `2026-11-10.c6a2d870`. All 20 expected versions and all 30 database target
hashes/sizes were verified against that committed index.

The [post-release dry-run monitor](https://github.com/Flow-Steward/extensions/actions/runs/42846402128)
succeeded for all **45 extensions, zero collection errors**. Exact report-key
comparison found **113 resolved events, 106 retained events, zero new events**.

| Findings | Before | After | Removed |
|---|---:|---:|---:|
| Security | 90 | 11 | 79 |
| Ordinary version updates | 129 | 95 | 34 |
| Total | 219 | 106 | 113 |

Every remaining security event is an upstream Toolbox source match covered by the
static applicability table above. No Go linked-module/standard-library or PyPI
security event remains in the report. This is limited to queried sources and
inventoried components; it is not a security certification. The 95 ordinary update
notices remain maintenance work, including a future Toolbox/driver migration and
the three explicitly constrained Python dependencies.

Existing coverage gaps remain visible: seven non-SQL connectors' upstream source
provenance format is unsupported by the monitor (unchanged from baseline), and
the local Neo4j driver replacement cannot be version-checked automatically. This
batch independently reviewed the source boundaries for all 15 connectors and
queried Neo4j's retained upstream 6.0.0 identity in addition to linked versions.
The normal report also lists unpinned development dependencies and pseudo-version
ordering gaps. Do not interpret an incomplete coverage area as an all-clear.

Downloaded report artifact SHA-256:
`9cc5e8bc553c637daa7b6bd4e562dbe1fe8bdd5cc28e0178ebd9631aaa20322d`.
Issue writes were disabled for this verification run; no issue closures are implied.
