# Extension Dependency Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Discover published official extension dependencies and raise deduplicated update/security issues on a schedule.

**Architecture:** Pure static discovery feeds bounded registry clients and an issue reconciler. The catalog selects source repositories and published tags; no extension code is executed.

**Tech Stack:** Python 3.12, PyYAML, packaging, urllib, pytest, GitHub Actions.

**Spec:** ../specs/2026-11-10-dependency-monitor-design.md

## Global Constraints

- Read only published versions from registered Flow-Steward repositories.
- Never execute or install inspected source; do not mutate generated catalog data.
- Dry-run by default; issues require explicit --write-issues.
- Report unknown coverage and partial failures; preserve human issue notes.

## Review Focus

- Owner filtering must include com.* IDs and exclude lookalike owners.
- Version ranges and unsupported sources must not become invented installed versions.
- Pagination, withdrawn advisories and closed issues must not create false/duplicate findings.
- Malformed/oversized files and truncated source trees must fail visibly.
- Credentials must only reach api.github.com, without authenticated redirects.

### Task 1: Dependency discovery

Files: scripts/dependency_inventory.py, scripts/test_dependency_inventory.py.
Interface: discover(files: dict[str, str], paths: list[str]) -> Inventory; immutable Dependency records with ecosystem, name, version, evidence and scope.

- [x] Write and run failing tests for official source selection, manifest/wheel/lock parsing, ranges, metadata and unsupported inputs.
- [x] Implement static discovery and pinned-source validation.
- [x] Format changed Python files and run focused tests in Docker.

### Task 2: Lookups, findings and issue reconciliation

Files: scripts/dependency_sources.py, scripts/monitor_dependencies.py, scripts/test_monitor_dependencies.py.
Interfaces: Services inventory/read/latest/vulnerabilities methods; scan_catalog produces a serializable report; sync_issues reconciles deterministic issue payloads.

- [x] Write and run failing tests for pinned refs, update comparisons, OSV pagination/withdrawals, failure isolation, deduplication and dry-run.
- [x] Implement bounded authenticated reads, cached lookups, deterministic findings and safe issue writes.
- [x] Run focused tests and a read-only live smoke check.

### Task 3: Scheduled operation and documentation

Files: .github/workflows/monitor-dependencies.yml, requirements-monitor.txt, README.md, docs/dependency-monitoring.md.

- [x] Add daily/manual workflow with minimal permissions, concurrency and always-uploaded reports.
- [x] Document coverage, limitations, manual invocation and issue lifecycle.
- [ ] Run full catalog tests, formatting and diff checks; independently review the whole change.
- [ ] Commit the reviewed implementation and prepare it for publication.

## Verification record

- Baseline: 184 catalog tests passed in a disposable Python 3.12 audit container.
- New discovery and reconciliation tests were run failing before implementation.
- Independent review found four issues; regression tests reproduced all four, fixes passed follow-up review.
- Live read-only GitHub/PyPI/OSV scan of image-processing and Docling completed with no transport errors.
- Live native Toolbox scan exercised 283 declarations; identified pseudo-version-only Go modules, now reported as coverage gaps while retaining vulnerability checks.
- No extension code was executed and no issues were created during local validation.
