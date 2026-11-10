# Security releases and accurate dependency monitoring

User-approved order: release compatible Image Processing and Snowflake security
updates first; then correct binary inventories and advisory deduplication.

- [x] Image Processing: Pillow >=13.0.0, architecture wheels and hashes, patch release,
  full compatibility tests, packaged archive validation and release delivery.
- [x] Snowflake: gosnowflake/v2 >=2.2.0, pinned reproducible build, both architectures,
  accurate provenance, driver-bound write regressions and release delivery.
- [x] Independently review the two release patches, publish only tested archives,
  and verify catalog records and target hashes after delivery.
- [x] Monitor: inventory verified published release archives, inspect Go build
  metadata statically for both architectures; do not attribute upstream go.mod
  modules to variants that do not contain them. Missing binary inventory must be
  a visible gap, not a claim of safety. Preserve provenance and target evidence.
- [x] Monitor: union overlapping advisory IDs/aliases, including multi-module
  advisories; preserve all IDs and sources. Match old issue markers across all
  historical aliases so an added alias does not recreate an acknowledged event.
- [x] Add failing regressions for runtime composition, per-architecture differences,
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

## Delivery checks

- Catalog publish run 42826858881 succeeded; index includes 0.2.2 and 1.3.2 with
  both architecture hashes. Published Image ZIP members match the tested local
  ZIP members byte-for-byte (ZIP container timestamps differ).
- First new monitor dry run 42827507363 exposed seven legacy provenance records
  with hashes/sizes but no path. A regression reproduced the failure; the path is
  now bound uniquely through SHA-matching, independently verified package metadata.
  Tampered provenance digest/size still fails. All 14 affected real archives parse.
- The compatibility correction was independently reviewed; 286 catalog tests pass.

- Final full dry run [42828802606](https://github.com/Flow-Steward/extensions/actions/runs/42828802606)
  on 9c5a5d1 succeeded: 45 extensions, 219 findings, zero errors, no issue writes.
  Daily scheduled issue reconciliation remains enabled on main.
- Image APNG/PNG EXIF advisories CVE-2026-112399 / CVE-2026-96643 and Snowflake
  driver advisory CVE-2026-86597 are absent from the updated report.
