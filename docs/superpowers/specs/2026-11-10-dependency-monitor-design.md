# Extension dependency monitoring

Approved direction: use the catalog's source repositories to discover dependencies
automatically, run on a GitHub Actions schedule, and open catalog issues for new
versions and published vulnerabilities. No hand-maintained per-extension inventory.

The monitor selects registered repositories owned by Flow-Steward and the published
versions in index.json. It resolves each published tag to a commit and statically
reads dependency metadata at that commit; it never executes extension code or
installs extension dependencies. Shared dependency lookups are cached per run.

Discovery covers extension.yaml Python requirements, requirements files, Python
project and lock files, committed wheel filenames, npm package locks, Go modules,
and GitHub components recorded in provenance/third-party metadata. Pinned upstream
Go module declarations are inspected where available. Unpinned dependencies,
unsupported manifests and lookup failures are reported as coverage gaps, never as
a clean security result. Remote service API changes and an exhaustive binary SBOM
are outside this first implementation; manifest declarations do not prove the
contents or reachability of a compiled binary.

Stable registry releases generate update findings. OSV package/version or commit
queries generate vulnerability findings, with affected extension versions and
source evidence. An update is a request to assess compatibility, not permission
to upgrade. All environments/markers are retained rather than evaluated on the
monitor runner. Development and build dependencies are identified separately.

One issue per dependency/event groups affected extensions. Stable machine markers,
pagination over open and closed issues, and workflow concurrency prevent duplicate
issues. Closed issues stay closed; a new release/advisory creates a new event.
Human notes outside the generated body section are preserved. No automatic fixes,
release publication, catalog mutations, or issue closure.

The workflow runs daily and manually, on the default branch only, with contents:
read and issues:write. It saves JSON and Markdown reports even on partial failure.
Network/source errors fail the run after preserving successful findings; coverage
limitations remain explicit in the report. Dry-run is the CLI default.

Alternatives considered: Dependabot alone does not cover this catalog's custom
manifests and provenance; a manually curated inventory duplicates source metadata.
The chosen approach is the user's catalog-driven static monitor.
