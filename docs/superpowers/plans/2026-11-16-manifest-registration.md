# Manifest-derived Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** One catalog CI command registers a released extension from its manifest and proves public catalog delivery.
**Architecture:** Catalog-owned Python helper reuses build_index archive/entry validation. A trusted manual workflow serializes with publish-index and commits records before generating the index. No Core changes.
**Tech Stack:** Python 3.12, PyYAML, pytest, GitHub Actions.
**Spec:** ../specs/2026-11-16-manifest-registration-design.md

## Global Constraints

Public Flow-Steward/ext-* source, stable tag, manifest-derived extension_id, no source execution or new credentials, ordinary push, no changed immutable releases, identical registrations are idempotent. No local clone/Docker/image resources.

## Review Focus

- Existing ID owned by another repository must never be replaced.
- Source/tag/manifest/archive identities must agree.
- Existing release bytes and icons must not be overwritten with changed inputs.
- Missing/stale/wrong-repository public items must not count as delivery.
- Workflow must never execute extension code with catalog write credentials.

### Task 1: Helper and behavioral tests

**Files:** create scripts/register_extension.py and scripts/test_register_extension.py.
**Interfaces:** register(repository, tag, manifest_path='extension.yaml', github=None) -> receipt dict with extension_id, version, repository, source_sha, registration_path, changed. verify_index(index, receipt, expected_item=None) validates schema, unique ID, active version at least requested, repository; verify_published(receipt, commit, expected_index, github=None, attempts=6, delay=5) performs bounded public readback and compares validated item.
- [ ] Write real-filesystem/fake-network tests using catalog archive fixtures; add CLI refusal and safe idempotence tests.
- [ ] Commit tests, open PR; hosted python -m pytest -q scripts must demonstrate missing implementation.
- [ ] Implement strict source/manifest/release validation with existing parse_entry/fetch_release and namespace policy; no local writes before preflight completes.
- [ ] Implement public-index checks, immutable commit readback, bounded network retry and actionable CLI errors.
- [ ] Run hosted suite, confirm behavior and commit.

### Task 2: Workflow and author integration

**Files:** create .github/workflows/register-extension.yml; modify scripts/new_extension_repo.py, scripts/test_templates.py, README.md, docs/automatic-extension-releases.md; tests in scripts/test_register_extension.py.
**Interfaces:** CLI register --repository --tag --manifest-path --receipt; verify --receipt --commit --expected-index.
- [ ] Test workflow write/source separation, concurrency, pinned actions and no untrusted shell interpolation; test generator output for first-party manifest identity/version.
- [ ] Observe RED, then add workflow pinned to ubuntu-24.04 and Actions v7/v7.1; inputs passed through environment. Reject non-main workflow execution.
- [ ] Register, use existing publisher to collect records, commit registration+records, build/verify local index, commit/push, then verify exact public commit.
- [ ] Print generated gh workflow command after new first-party repository preparation; preserve generic third-party behavior.
- [ ] Document command, idempotent reruns, stable/public requirements and diagnostics; run catalog suite and CodeQL.

### Task 3: Review and live proof

- [ ] Review immutable final branch, fix findings, recheck main and merge only passing candidate.
- [ ] Run register-extension.yml on main for Flow-Steward/ext-finance-b1 tag v0.1.0.
- [ ] Require canonical existing path, changed=false, public readback containing B1 and expected archive identity; no new extension release, unchanged registration and catalog.
- [ ] Save compact JSON evidence, report command/PR/run and coverage. No Core modifications.
