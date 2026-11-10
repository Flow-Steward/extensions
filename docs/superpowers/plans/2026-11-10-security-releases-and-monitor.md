# Security releases and accurate dependency monitoring

User-approved order: release compatible Image Processing and Snowflake security
updates first; then correct binary inventories and advisory deduplication.

- [x] Image Processing: Pillow >=13.0.0, architecture wheels and hashes, patch release,
  full compatibility tests, packaged archive validation and release delivery.
- [x] Snowflake: gosnowflake/v2 >=2.2.0, pinned reproducible build, both architectures,
  accurate provenance, driver-bound write regressions and release delivery.
- [ ] Independently review the two release patches, publish only tested archives,
  and verify catalog records and target hashes after delivery.
- [x] Monitor: inventory verified published release archives, inspect Go build
  metadata statically for both architectures; do not attribute upstream go.mod
  modules to variants that do not contain them. Missing binary inventory must be
  a visible gap, not a claim of safety. Preserve provenance and target evidence.
- [x] Monitor: union overlapping advisory IDs/aliases, including multi-module
  advisories; preserve all IDs and sources. Match old issue markers across all
  historical aliases so an added alias does not recreate an acknowledged event.
- [ ] Add failing regressions for runtime composition, per-architecture differences,
  tampered archives, conflicting alias chains and existing closed issues. Run all
  catalog tests and a complete dry run, review, merge and verify scheduled workflow.

Implementation choices: retain existing extension host contracts, native SQL
parameter patch and catalog publication protocol. No live Snowflake compatibility
claim without a test account. Use deterministic fixture validation plus driver Go
unit tests and report that limit. Binary parsing never executes inspected binaries.

## Release evidence

- Image Processing v0.2.2: commit ef33250c74e334ead110e75b6a9c7faccb5e8cf0;
  both archive suites 54 passed, package validation and offline dependency checks;
  GitHub release workflow 42824212916 succeeded.
- Snowflake v1.3.2: commit 95e47f99cc6670268cb5d515ff5a82b60cfbe41f;
  extension suite 170 passed/74 skipped, offline driver log-redaction and bound-write
  Go regressions passed; both target archives validated and released. No live account.
- Both release patches independently reviewed. Monitor review also approved after
  reference-retention and official Go release-link regressions were added.
- Catalog publication and full Actions dry run are delivery verification steps.
