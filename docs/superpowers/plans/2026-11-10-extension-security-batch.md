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
- [ ] Prepare one pinned Go module security baseline against exact Toolbox v1.3.0
  b0010060a939455d91e4f8ba62dc3e72b1892469 and official Go 1.26.10 image
  sha256:5de7c99eb78ca5e515a4c340235d0955ec5964a5071c492c15503d7c267da473.
  Add a dependency-floor regression, observe RED on old payload, then GREEN on
  rebuilt metadata. Query the resulting exact modules with OSV.
- [ ] SQL variants (postgres, mysql, oceanbase, singlestore, mssql): apply baseline,
  preserve existing native patches, bump patch versions, rebuild both targets,
  run native bound-query regressions + extension compatibility suites, validate ZIPs.
- [ ] Specialized SQL/cloud (clickhouse, snowflake, spanner): same gates, preserving
  Snowflake driver >=2.2.0, compression and identity compatibility.
- [ ] Native non-SQL variants (bigquery, firestore, mongodb, neo4j, oracle, redis,
  valkey): same baseline/gates, preserve custom mains/driver forks/safety controls.
- [ ] Other affected Python extensions: file-transfer, typesafe-ai, example-showcase,
  google-cloud-vertex and Image Processing; update compatible affected pins/wheels,
  retain legitimate behavior, rebuild both targets where applicable and validate.
- [ ] Fresh independent bypass/regression review before publishing each group.
- [ ] Publish tested release assets, verify catalog versions and hashes, run full
  read-only monitoring, compare baseline keys, explain retained/unreachable signals.

Review focus: only actual shipped modules; per-architecture provenance; readonly
module checks; no accidental SQL/endpoint/redirect safety regression; unchanged
Python host protocol and optional dependency behavior; max 50 MiB release archive.

Execution: fix-finding owns the security gates. Independent repositories may be
handled in parallel under dispatching-parallel-agents; root integrates and publishes.

Execution evidence:
- Read-only boundary investigation confirms fixed stdio execution and bespoke
  native patch differences (SQL variants, BigQuery, Firestore, Neo4j, Redis/Valkey).
- Shared module patch SHA256 a6623600324d2bdec1b30102e749678d4fea326bbb9d9f4f586a7ba472d395e2;
  go.mod 7f367f79f68cc28cfcb8c7d36c5533ef79f5016aaeba4443a795a46132105fb5;
  go.sum ca2ace78373b79e7c2b048e69ef22abfb93f1b3a537b7f035ad7c1a0c28542e9.
- Official OSV queries for all 15 selected module/toolchain versions return zero
  known non-withdrawn matches and no pagination. Full post-release run is still needed.
- Real old SQL binaries and specialized SQL release binaries observed RED for
  old go1.26.2 against new minimum1.26.10.
- Python SFTP candidate constraints: aiobotocore3.10.0 requires botocore>=1.43.115,
  <1.43.118 and python-dateutil<3; incompatible newest independent pins will not
  be forced. Compatible botocore1.43.117 and dateutil2.9.0.post0 retained as needed.
