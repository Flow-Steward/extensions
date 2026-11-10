# Monitoring published extension dependencies

The **Monitor extension dependencies** workflow runs daily at **06:43 UTC** and
can be run manually from Actions. Scheduled runs create/update issues in this
catalog. Manual runs default to **dry run**; clear that checkbox to write issues.
The workflow must be on the repository's default branch to run. GitHub may delay
schedules; public repositories with no activity for 60 days can have schedules
disabled. Check the Actions run history if reports stop arriving.

No extra token or per-extension configuration is needed for public repositories.
The workflow's `GITHUB_TOKEN` reads public source metadata and writes issues only
in this catalog. Inspected extension source is never executed or installed. HTTP
credentials are sent only to api.github.com. API redirects are refused; release
downloads carry no credentials and follow only GitHub asset-host redirects.

## Selection and discovery

The monitor reads `extensions/*.yaml`, selects the exact GitHub owner
`Flow-Steward`, and joins those registrations to **published** entries in
`index.json`. IDs such as `com.image.processing` are included. Deprecated and
unregistered entries are excluded. It verifies each source URL and version,
resolves the published `v<version>` tag to a commit, and reads that immutable
source tree for the rest of the run. It never edits catalog entries or release
records. The report records the resolved commit for auditability.

| Source metadata | Coverage |
|---|---|
| `extension.yaml` / `python_requirements` | Runtime package pins |
| `requirements*.txt`, `requirements*.in`, constraints and requirements directories | Pinned Python declarations, includes and hashes; all environment markers retained |
| Committed `.whl` filenames | Exact package versions, including architecture-specific wheels and development wheels |
| `pyproject.toml` | PEP 621 runtime/optional and build requirements |
| `uv.lock`, `poetry.lock` | Public PyPI locked versions, including transitive entries |
| `package-lock.json` v2/v3 | npm locked versions, including transitive entries |
| `go.mod` | Required modules and versioned replacements; local replacements are gaps |
| `*-provenance.json`, `THIRD_PARTY.yml` | GitHub source, tag/version and commit fields used by maintained native components |
| Published release ZIPs | SHA-256/size verified against the catalog; runtime wheels and actual Go build metadata, separately for each target |

Published archives are inspected without extracting, executing or installing their
contents. Target package metadata and native-file hashes are checked; Go ELF build
metadata supplies the modules actually compiled into each binary and its Go
standard-library version. The monitor does not attribute a shared upstream
`go.mod` to every database variant. Runtime wheels exclude `dev-wheels`; source
build/development declarations remain visible with their own scopes.

This remains a static inventory, not an exhaustive binary SBOM or reachability
analysis. Unsupported/missing native build metadata is an explicit coverage gap.
Python wheel dependencies are not recursively resolved; libraries absent from
both declarations and supported binary metadata are not inferred. A dependency's
presence does not establish that a vulnerable operation is reachable.

Development/build dependencies are included and identified in findings. Unpinned
ranges are not treated as installed versions. Unsupported manifests (including
Docker, Yarn and Cargo), custom registries, missing included files, direct URL
requirements, and absent dependency declarations appear under **Coverage**.
Arbitrary include filenames outside supported requirements paths are reported as
missing rather than fetched as executable or unconstrained content.

Changes to external SaaS APIs, API retirement dates and remote product releases
that are not declared dependencies are **not monitored** by this workflow. For
example, an HTTP client dependency does not describe Shopify's API lifecycle.
Those need a separate source adapter with reliable product/version identity.

## Findings and issue lifecycle

- Update sources: PyPI, npm's `latest` tag, the Go module proxy, official Go stable-release metadata and GitHub releases.
  PyPI yanked/empty releases and prereleases are excluded. Latest stable versions
  are candidates for review, not assertions of runtime compatibility. Go proxy
  version lists may contain retracted releases; assess upstream release notes.
  Modules with only Go pseudo-versions have an explicit update-coverage gap;
  their exact pseudo-version is still queried for vulnerabilities.
- Vulnerabilities: OSV queries use exact ecosystem/package/version or upstream
  commit, paginate results and ignore withdrawn advisories. Fixed versions from
  the relevant package's advisory are included when present. No OSV match means
  **no known match in that source**, not proof of safety or complete coverage.
  Python compatibility builds with a PEP 440 local suffix retain the complete
  installed version in the report, while vulnerability queries use its public
  upstream version. A local suffix such as `+flowsteward.1` therefore cannot hide
  known upstream advisories. The extension owns its patches and provenance;
  this conservative lookup does not assume a local patch fixes an advisory.
- Updates retain one deterministic issue marker per dependency/release event.
  Security advisories are grouped by the transitive union of their primary IDs
  and explicit aliases, including advisories covering multiple Go modules.
  Every affected package/version/extension/target, advisory ID, source reference
  and component-specific fixed-version detail is retained.
- Repeated runs match both the canonical advisory marker and historical markers
  for known aliases and packages. Adding a CVE alias therefore also matches an
  old OSV issue. Closed issues are respected; open legacy generated sections are
  migrated while preserving human notes. Only `github-actions[bot]` issues are
  reconciled. Existing duplicate issues are not automatically closed.
- Issues are not automatically closed or reopened. Closing an issue records your
  decision for that event; review applicability, update/test the extension and
  publish through its normal release workflow when appropriate.
- The first run reports all currently detectable updates/advisories; it does not
  silently baseline existing problems. It can create several issues.

The scan caches shared lookups for the duration of each run. Source/registry
failures do not hide findings from other extensions: the run preserves its
partial report, attempts to publish successful findings, and exits unsuccessfully.
Existing issue bodies are preserved on partial scans so missing data cannot remove
previously affected extensions. New independent findings can still create issues.
An individual damaged issue or failed write is reported without blocking other
issues; the next run can retry failed events.
Coverage gaps alone are warnings, not a green assertion of complete coverage.
Malformed source metadata is reported as a gap; transport failures fail the run.

Every run uploads `dependency-report.json` (inventory, findings, errors) and
`dependency-report.md` (human summary) for 30 days, and writes the summary to the
Actions run. Setup/test failures explain why no report was produced.

## Local read-only checks

Use Python 3.12 or later in an isolated environment:

```bash
python -m pip install -r requirements-monitor.txt
python scripts/monitor_dependencies.py --output-dir /tmp/extension-monitor
python scripts/monitor_dependencies.py --extension com.image.processing \
  --output-dir /tmp/extension-monitor-smoke
python -m pytest -q scripts
```

`GITHUB_TOKEN` is optional for local read-only checks but avoids GitHub's low
unauthenticated rate limit. Issue writes require `--write-issues`, a complete
unfiltered scan, and the destination repository's GitHub Actions environment.

API references: [OSV queries](https://google.github.io/osv.dev/post-v1-query/),
[PyPI JSON API](https://docs.pypi.org/api/json/),
[GitHub issues](https://docs.github.com/en/rest/issues/issues),
[scheduled workflow behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).


## Maintenance results

The [2026-11-10 maintenance batch](extension-maintenance-2026-11-10.md) records
20 published releases, compatibility decisions, retained advisory applicability,
coverage limits and the exact before/after monitor comparison.
