# CodeQL advanced setup implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this migration, with an independent workflow review.

**Goal:** Replace GitHub-managed CodeQL default setup in the catalog and 49 public extension repositories with working advanced workflows pinned to `ubuntu-24.04`.

**Architecture:** Each repository owns `.github/workflows/codeql.yml`, with an explicit language matrix and SHA-pinned Node24 actions. Preserve the default query suite and existing languages; include Actions coverage for the new workflow. Scan pushes, pull requests, and a staggered weekly schedule. Add weekly GitHub Actions Dependabot updates for the pinned scanner.

**Tech stack:** GitHub Actions, CodeQL v4, GitHub-hosted Ubuntu 24.04, Dependabot.

**Spec:** The user's explicit request to migrate CodeQL to advanced setup while excluding the main application.

## Global constraints

- Exclude `Flow-Steward/flow-steward-app` entirely.
- Use `ubuntu-24.04`, SHA-pinned Node24 actions, and existing default CodeQL queries.
- Preserve Python in all repositories, JavaScript/TypeScript in Google Workspace, and Go in Firestore.
- Keep `/language:<language>` categories, existing alert state, and free public-repository scanning.
- Do not enable paid or AI features, change runtime dependencies, or publish extension versions.

## Review focus

- Default setup must be replaced, not left alongside an ignored custom workflow.
- Required languages and real source extraction must be preserved, including Firestore's dependency-locked native Go build.
- Keep contents read-only; grant only the analysis job `security-events: write`.
- New scan jobs must use Ubuntu 24.04 and upload successful analyses without migration notices.
- Existing extension CI/release workflows and alert dismissals remain outside this patch.

## Tasks

- [ ] Snapshot current settings in all 50 repositories and prepare isolated extension checkouts.
- [ ] Add and validate the catalog workflow, Dependabot config, and reusable templates; obtain independent review.
- [ ] Switch catalog default setup to advanced and publish the prepared files; verify both analyses and runner labels.
- [ ] Generate extension configurations from the settings inventory. For Firestore, restore and verify existing locked Go module files only in CI, then compile original native sources under CodeQL.
- [ ] Validate YAML, action pins, language coverage, permissions, triggers, and existing relevant workflow tests; review the special Go build.
- [ ] Switch each extension to advanced immediately before publishing its prepared commit. Do not leave any repository without a replacement workflow.
- [ ] Wait for all language analyses to upload successfully, inspect annotations, preserve evidence, and remove temporary clones.
