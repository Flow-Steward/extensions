# Automatic extension release CI

The user requires every active first-party extension repository to publish through CI and commands; manual ZIP uploads are discontinued. Descriptions remain authoritative in each extension manifest. flow-steward-app is excluded.

Existing tag-triggered pipelines are retained where they already test, build and publish correctly. Repositories without publication CI receive a small caller workflow backed by shared, SHA-pinned catalog tooling. Missing test/build gates in existing pipelines are corrected. New tags, never moved existing tags, trigger releases.

Build jobs use read-only repository access and no shared caches. They validate tag/manifest/descriptor identity, prepare explicitly declared runtime payloads, run repository checks, package every declared target and inspect archives with the catalog checker. Publish jobs use only the caller repository contents token and consume SHA/size-bound build artifacts; no source code runs in that privileged job. No new credentials, AI features or application code are introduced.

Some native executables are distributed in existing releases rather than Git. A checked-in per-repository recipe pins their source release URL, size, SHA-256 and exact restore paths. CI accepts only same-repository HTTPS assets, rejects archive traversal and symlinks, restores only declared artifacts, and requires their identity to match current tracked provenance/security checks. Changed provenance or payload identities fail closed until the recipe/source build is updated. Existing untracked packages.txt inventories are preserved. Native binaries are not silently replaced or downgraded.

The source repository packager is used where present; a deterministic tracked-file packager covers Amazon and Qdrant. Both Linux target archives are validated where declared; portable archives retain their portable contract. Existing convenience release assets are preserved. Published releases/assets are immutable: reruns verify identical artifacts or stop, never clobber them.

Catalog publication remains generated from release manifests and immutable assets. It is automatically refreshed by its existing schedule; optional notification may use only an already configured catalog-scoped token. No source-controlled editorial override is added.

Alternatives considered: hand uploads (rejected by user); separate runtime rebuilds for metadata-only releases (unnecessary and would change binary provenance); shared validated CI with declared payload inputs (selected under explicit delegation to choose and publish).
