# Automatic Extension Release CI Implementation Plan

> **For agentic workers:** Execute scoped independent implementation/review tasks under dispatching-parallel-agents; evidence before publication.

**Goal:** CI builds, validates and publishes releases for all 46 active first-party extension repositories, without manual ZIP uploads.
**Architecture:** SHA-pinned shared catalog tooling and reusable workflows, with per-repository declarative recipes for source packaging and verified native payload restoration. Existing working workflows remain intact unless a gate is missing.
**Tech Stack:** Python 3.12, PyYAML, pytest, GitHub Actions, GitHub CLI on hosted runners.
**Spec:** docs/superpowers/specs/2026-11-11-automatic-extension-release-ci.md

## Global Constraints
- Never read/change/run the main application repository.
- Source manifests are the only customer-description source.
- No manual ZIP publication, moved tags, clobbered assets, new credentials or paid AI.
- Execute checks in disposable containers or requested hosted workflows; preserve logs and exact SHAs.

## Review Focus
- A wrong tag, extension id, descriptor, target or archive digest must stop publication.
- Declared payload downloads must not write outside the checkout or restore arbitrary source.
- A changed native provenance/floor must never accept an old binary silently.
- Fork/PR builds must never receive publication permissions or publish artifacts.
- Reruns must preserve existing immutable releases and optional companion assets.

### Task 1: Shared release tooling
- [ ] Add scripts/release_extension.py and focused tests before implementation.
- [ ] Cover identity mismatch, malformed recipe, unsafe archive path/symlink, wrong hashes, target mismatch, missing binary, changed provenance, source packager failure and deterministic outputs.
- [ ] Verify in disposable Python 3.12; inspect real source recipes and representative native/portable archives.

### Task 2: Workflows and recipes
- [ ] Add reusable read-only build/validate and isolated publication workflow(s), pinned official action SHAs.
- [ ] Configure the 22 repositories lacking release workflows; audit the other24 and fix missing gates.
- [ ] Preserve each repository test selection, runtime payloads, convenience assets and version identity.
- [ ] Bump new patch versions where new CI source must enter an immutable tag.

### Task 3: Review, publish and complete cycle
- [ ] Independent review of tooling, trust boundaries and caller recipes.
- [ ] Commit/publish shared tooling, pin callers to its accepted SHA, then verify source CI.
- [ ] Push new tags via Git; watch release workflows, diagnose failures and retry scoped failed jobs.
- [ ] Verify every release's manifest descriptions and targets in generated catalog index.
- [ ] Preserve receipts/screenshots, clean only task-owned runtime resources and checkouts.
