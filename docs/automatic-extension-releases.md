# Automatic first-party extension releases

First-party extension releases are built and published by GitHub Actions. The source
`extension.yaml` supplies the description used by both the platform catalog and the
public website. ZIP files are CI artifacts, not hand-uploaded release inputs.

## Release command

After updating the manifest, descriptor and other current version metadata, commit
and push the source changes. The main/PR build validates the declared standalone
tests and every supported archive. Then publish an immutable matching tag:

```sh
git tag v1.2.3
git push origin v1.2.3
```

The tag workflow runs the tests again, builds the archives, validates their catalog
contract, uploads this run's artifacts and creates a GitHub Release. Only the isolated
publication job has repository Contents write permission. A manual workflow dispatch
can retry an existing tag; it cannot replace published bytes or move the tag.

New first-party repositories use `.github/release-config.json` and SHA-pinned calls
to `.github/workflows/build-extension.yml` and `release-extension.yml` in this repository.
The recipe declares `schema_version: 1`, `extension_id`, `runtime_targets`,
`test_requirements`, `test_paths`, `additional_assets` and optional `package_script`.
Optional `notes_file` must identify a declared additional asset. Portable packages use
`runtime_targets: [""]`; Linux variants declare both `linux-amd64` and `linux-arm64`.
Source packagers exclude `.github` so CI configuration stays outside runtime packages.

## Native runtime payloads

A missing ignored runtime binary can be restored from an explicitly declared,
same-repository prior release asset. Each `payload_sources` entry binds its URL,
size, SHA-256, target and exact `restore_paths`. The helper rejects path traversal,
symlinks, a different extension identity and attempts to overwrite differing source.
The source packager still enforces the tracked native provenance/security baseline.
Changing that baseline requires producing the corresponding new native binary and
updating the pinned input; the release does not silently reuse an old binary.

Published-only dependency inventories are preserved where required. The shared
workflow installs a verified first-party SDK wheel from an immutable public commit
because SDK0.4.0 is not published on PyPI. No application checkout or private test
implementation is imported. CI recipes explicitly select standalone tests; live
provider/database and application integration suites remain separate coverage.
Native identity checks execute both architectures on the hosted Linux runner.

## Publication and catalog delivery

The release plan binds the repository, tag, source commit, extension ID, targets,
asset names, sizes and SHA-256 digests. The publisher rechecks the complete plan and
catalog archive contract using immutable trusted tooling. It verifies the remote tag
commit and creates a release once. An existing public release succeeds only if the
complete asset set and downloaded bytes match. Drafts, mismatches and missing assets
stop the run; no clobber/upload replacement or tag mutation is used.

The existing catalog publish workflow discovers releases on its schedule. Existing
optional dispatch integration can announce them immediately; no new cross-repository
credential is required. A catalog workflow dispatch is also available for bulk release
verification. The generated index records the source-manifest listing fields.

## Evidence

Shared tooling tests cover unsafe restoration, altered hashes, wrong identity/targets,
source packager failure, native sidecars and immutable publication behavior. The
release workflow tests enforce the read-only build / isolated publisher boundary.
Archive validation is the catalog contract check; it does not claim a full application
installer or live-provider integration run.

## Runner baseline

Catalog and first-party extension workflows use `ubuntu-24.04` explicitly.
This keeps the OS release stable while the image continues receiving updates;
it avoids inheriting a new Ubuntu release through `ubuntu-latest`.
Reusable workflow callers pin the catalog commit that declares this baseline.
