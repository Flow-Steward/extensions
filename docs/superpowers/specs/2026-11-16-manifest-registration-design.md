# Manifest-derived extension registration

Date: 2026-11-16

## Intent and scope

Replace hand-written first-party catalog registrations with one command in Flow-Steward/extensions. A maintainer supplies an already public source repository and stable release tag; the workflow derives the filename from the tagged manifest and verifies the public catalog after publication. No Core or extension runtime changes, new credentials, source execution, release asset uploads, or cross-repository permission grants.

## Approaches

The maintainer selected one catalog CI command. It uses the catalog's existing job token and works without changing every extension release workflow. Automatic calls from all extension release workflows were considered; those require a separate rollout and cross-repository authentication, so are outside this change.

## Command and behavior

`gh workflow run register-extension.yml --repo Flow-Steward/extensions -f repository=Flow-Steward/ext-finance-b1 -f tag=v0.1.0`

An optional manifest_path defaults to extension.yaml for repositories with more than one manifest.

1. Resolve the stable tag to a source commit. Read the manifest from that commit, never execute source code. Require a public Flow-Steward/ext-* repository, a valid dotted extension_id, and a manifest version matching the release tag.
2. Validate the public release archives with the existing catalog checker, including archive identity, target layouts, icons, sizes and hashes. Use the existing namespace policy.
3. Generate only extensions/<extension_id>.yaml, with the canonical repository URL. Accept an identical existing registration without rewriting it. Reject conflicting repositories, unsafe paths, changed existing release bytes, missing releases and malformed manifests before publication.
4. Reuse the catalog's publication pipeline to record releases/icons and rebuild the index. Serialize with the existing publish-index concurrency group. Commit records before index generation so icon URLs stay pinned; push normally, without force.
5. Read the index from the exact public commit just pushed and require the expected ID, repository and an active release at least as new as requested. Validate the selected item's archive identity against the generated/validated index. Missing/wrong/stale entries or unavailable public readback fail the job with a specific diagnostic; never report a release as delivered just because a GitHub Release exists.

## Integration

Add a catalog-owned registration/verification helper and the manual workflow. Document the command in the catalog README and automatic-release guide. The repository generator prints the same command with its manifest version, so authors no longer invent registration filenames. Existing manual PR submissions and scheduled updates remain supported.

## Verification

Hosted tests cover manifest-derived names (including B1 versus ext-finance-b1), malformed identities/versions/paths, ownership and namespace restrictions, conflicting versus identical registrations, invalid archives, public-index missing/stale/wrong-repository cases, bounded readback retries, and workflow privilege/concurrency boundaries. Verify the new helper's tests fail before implementation, then run the catalog suite and CodeQL. After merge, run the actual command for an already registered extension to prove idempotence and published catalog readback without issuing a new extension version.
