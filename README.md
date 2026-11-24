# Flow Steward extension catalog

Extensions for [Flow Steward](https://github.com/Flow-Steward/flow-steward-app).
Flow Steward reads [`index.json`](index.json) and lists these extensions under
**Extensions → Marketplace**, where an administrator installs them in one click.

Every extension lives in **its author's own GitHub repository**. This catalog
only holds a link to it, and publishes the author's releases automatically.
`index.json` and everything under `releases/` are generated; never edit them.

## Share an extension

For Flow Steward maintained `ext-*` repositories, use [automatic registration](#automatic-first-party-registration)
after publishing the release. It derives the filename from the manifest; do not
write registration files by hand. Steps 1–4 below still describe release requirements.

1. Keep the extension in its own public GitHub repository with `extension.yaml`
   at the repository root. Check it with
   `flow-steward extensions validate <extension_id>`.
2. In `extension.yaml`, make sure it has:
   - a readable `display_name` and a `description` of at least 40 characters;
   - `listing.category`, one of the ids in [`categories.json`](categories.json). The same list,
     with the names Flow Steward shows, is used by the
     [workflow catalog](https://github.com/Flow-Steward/workflows), which keeps a copy of this file;
   - optionally `listing.categories`, a non-empty list of distinct ids from that
     same list, for every additional function the extension actually implements.
     The primary `listing.category` stays first. For example, WordPress with
     WooCommerce belongs to both `cms` and `ecommerce`. Classify the extension's
     implemented operations, rather than everything its upstream product can do;
   - optionally `listing.summary` (the card line; otherwise the first sentence of
     the description), `listing.tags` and `listing.setup_summary`.
   - `runtime.contract_version: extension_host_v2` (build on
     `flowsteward-extension-sdk` 0.4.0 or later).
3. Put your logo in the bundle: a file named `icon.png` next to
   `extension.yaml`. There is no manifest field; the file name is the contract,
   so replacing that one file is all it takes. Rules (the same as the MCP
   catalog's icons): PNG only (no SVG), square, 32–512 px (128×128
   recommended), at most 100 KB. `flow-steward extensions create` writes a
   neutral "package" logo you can replace; a release without a valid `icon.png`
   is refused here and by Flow Steward's installer. The catalog keeps its own
   copy of each release's icon (`releases/<extension_id>/<version>.png`), so the
   index links an image that cannot change.
4. Publish a release: tag `v<version>` (the same version as `extension.yaml`)
   with the asset `<extension_id>-<version>.zip`, whose files sit under one top
   folder named after the id with `.` and `-` replaced by `_`
   (`acme.crm-sync` → `acme_crm_sync/`). Copy
   [`templates/release-extension.yml`](templates/release-extension.yml) into your
   repository's `.github/workflows/` and it does this for every tag you push.
5. Open a pull request here adding one file, `extensions/<extension_id>.yaml`:

   ```yaml
   repository: https://github.com/<owner>/<repo>
   ```

   Use the exact `.yaml` suffix and put the file directly in `extensions/`.
   Other filenames and subdirectories fail validation and publication instead
   of being skipped. The existing `.gitkeep` placeholder is allowed.

   Open it from the repository owner's account, or as a public member of the
   owning organization. The **Validate submission** check downloads your latest
   release and tells you what to fix.

After the merge your latest release is listed within minutes.

### Automatic first-party registration

After the first public release, run one command (or open **Actions → Register
extension and verify catalog delivery → Run workflow** on the catalog's main branch):

```sh
gh workflow run register-extension.yml --repo Flow-Steward/extensions \
  -f repository=Flow-Steward/ext-finance-b1 -f tag=v0.1.0
```

Replace the repository and published stable tag with yours. For a variant manifest,
add `-f manifest_path=variants/b1/extension.yaml`. The workflow reads that file from the
resolved tag commit and derives `extensions/<extension_id>.yaml` itself, validates
the public archives, publishes the index, then reads the exact public commit back
to verify the ID, active version and archive identity. It never executes extension
code. Only public `Flow-Steward/ext-*` repositories are accepted.

The workflow uses the catalog's existing job token; no token from the extension
repository is needed. Maintainers with permission to run catalog workflows can
use it. The repository preparation script prints the same command automatically.

Identical registrations are safe to repeat. An ID pointing to another repository,
a moved source tag, changed existing release bytes, an invalid archive, or missing
catalog delivery fails with a diagnostic. A retry does not replace a published ZIP
or create a new extension version. Subsequent releases continue to be discovered
on the existing schedule; use the command again when explicit delivery verification
is needed. External authors continue to submit the registration by pull request.

### An extension with a native executable

The installer accepts one architecture per archive, so attach one per runtime
target instead of a single archive: `<extension_id>-<version>-linux-amd64.zip`
and `<extension_id>-<version>-linux-arm64.zip`, each built with
`flow-steward extensions bundle --runtime-target <target>` (only that target's
`bin/<target>/` and its `.fs-package.yaml`). `linux-amd64` is required. Flow
Steward installs the archive for the architecture it runs on.

An extension whose Python wheels are built per architecture (numpy, onnxruntime,
cryptography...) is packaged the same way, without a binary: each archive keeps
only the wheels that install on its target, and `.fs-package.yaml` names the
target alone. `templates/single-extension` does this automatically when `wheels/`
holds architecture-specific wheels.

### Flow Steward maintained database extensions

Each maintained database has its own installable extension and public repository,
with its own database name, connection settings and driver. For example, PostgreSQL,
MySQL and Microsoft SQL Server live in `ext-data-postgres`, `ext-data-mysql` and
`ext-data-mssql`. Install only the databases you use. Build tooling and upstream
sources may be shared, while each architecture archive contains only its database's
runtime payload and required notices.

The existing `flowsteward.data-connector-mcp-toolbox-<database>` ids stay stable when
those extensions move to their individual repositories, so existing installations
can receive upgrades. The old shared repository remains historical provenance;
no active maintained database registration points to it.

SQLite is withdrawn from the catalog: its registration, release records and
icons have been removed, so no active or deprecated SQLite card is listed.
Reintroducing it requires a separately approved, working Dataset integration.

The PostgreSQL package includes SQL operations and optional pgvector collection,
document, chunk and similarity-search operations. Enable pgvector on the database
server before using vector operations; no second Flow Steward extension is needed.
The separate pre-release pgvector catalog entry is replaced by PostgreSQL.

### Several extensions from an author's repository

The catalog also supports an author publishing several extensions from one
repository. Each extension has its own entry file and id, and each release tag
carries every member's archives. This generic catalog capability does not change
the one-database-per-extension layout of maintained database repositories.

### Moving an existing extension into its own repository

```bash
python3 scripts/new_extension_repo.py <extension folder> ../ext-<kind>-<name> \
    --repository https://github.com/<owner>/ext-<kind>-<name>
```

copies the extension's tracked files, adds the CI and release workflows from
[`templates/single-extension/`](templates/single-extension) (tests on every push,
the archive checked with this catalog's own checker, a GitHub Release per tag)
and points the manifest's support and website links at the new repository.
Name repositories `ext-<kind>-<implementation>`, for example `ext-llm-openrouter`
or `ext-data-postgres`, and tag them with the topic
`flow-steward-extension`.

### New versions

Push a new tag in your repository. The catalog checks every listed repository
every five minutes and publishes each new release that passes the same checks — no pull
request needed. A release that fails is reported in the catalog's Actions log and
the previous version stays listed.

### Immediate delivery from Flow Steward maintained repositories

The catalog also accepts `repository_dispatch` with event type
`extension-released`. Maintained extension release workflows may send it after
all release assets have been published. The catalog still scans its registered
repositories and validates their assets; the event payload cannot add or alter
catalog entries.

The sender uses the Actions secret `CATALOG_DISPATCH_TOKEN`: a fine-grained token
scoped only to `Flow-Steward/extensions`, with **Contents: write** on that target
repository. Its ordinary `GITHUB_TOKEN` reads the source release only and cannot
replace this cross-repository credential. An organization secret can make the
token available to selected maintained extension repositories. Never place its
value in a workflow, release archive, log or patch.

A failed notification must be visible and must leave the published release and
its assets intact. In the maintained workflows, use **Run workflow** on the
source repository's default branch and supply the existing `release_tag` to
retry notification only; the tag check, CI and release-creation jobs are skipped.
Do not retag, delete or rebuild a release just to retry catalog delivery.
Polling remains the fallback, including for public authors who do not have a
catalog dispatch credential; GitHub can delay scheduled runs.

### What the checks refuse

- an entry that is not exactly `repository: https://github.com/<owner>/<repo>`;
- a submitter who does not own the repository;
- the `flowsteward.` namespace, which is reserved for github.com/Flow-Steward
  (see [`verified_publishers.json`](verified_publishers.json)). The catalog is
  where that is enforced: Flow Steward itself installs any id, from here or as an
  uploaded archive, as WordPress installs any plugin;
- a release whose `extension.yaml` names another id or version than the entry and
  the tag, or whose `extension-descriptor.yaml` disagrees with it;
- a release that declares a Dataset Connector registry but omits
  `dataset_connector` from `features`, which would hide its working integration
  from the marketplace capability filter;
- a release whose `extension.yaml` does not declare
  `runtime.contract_version: extension_host_v2`, the one host contract Flow
  Steward 1.0 runs (build it on `flowsteward-extension-sdk` 0.4.0 or later). A
  release recorded before this check is kept in `releases/` as history but is no
  longer listed; the extension is listed again from its next v2 release;
- a release without `icon.png` next to `extension.yaml`, or with one that is not a
  square PNG of 32–512 px and at most 100 KB;
- files outside the one top folder, symbolic links, `.env` and key files, a value
  under a key such as `password` or `api_key`;
- a native executable in a single archive, or a per-target archive that carries
  another target's `bin/`, a binary whose SHA-256 or ELF architecture differs from
  its `.fs-package.yaml`, or one without the executable bit;
- an archive over 50 MB (150 MB unpacked), Flow Steward's own install ceiling;
- a pull request that edits `releases/` or `index.json`, or moves a listed
  extension to another repository (a maintainer does that).

## Integrity

When a release is first published, its asset's URL, size and SHA-256 are recorded
in `releases/<extension_id>/<version>.json` and never change. Flow Steward
verifies that digest, and that the archive's own `extension.yaml` names the
release, before it installs anything. Every hour (the five-minute runs only record new releases) the catalog downloads
the listed asset again: if its bytes changed, that release is withdrawn and the previous one
is listed instead. Removing an entry keeps the extension listed as **deprecated**.

## What the catalog shows, and where it comes from

| Field | Source |
| --- | --- |
| Name, summary, description | `display_name`, `listing.summary`, `description` |
| Categories | `listing.category` plus optional `listing.categories`; reviewed release-specific corrections below |
| Capabilities | `features` |
| Permissions | `required_scopes` |
| Setup | `listing.setup_summary` |
| Tags | `listing.tags` (kept for the future marketplace, not shown yet) |
| Documentation link | the repository at the release tag |
| Download URL, size, SHA-256 | the release asset, recorded once in `releases/` |
| Logo (`icon`: URL, SHA-256, bytes, `image/png`, `WxH`) | the release's `icon.png`, copied once to `releases/<extension_id>/<version>.png` and linked at the catalog commit that added it |
| Verified | the exact repository, extension id and release version are selected in `verified_extensions.json` |

### Authorship and tested releases

`verified_publishers.json` reserves namespaces for authorized repository owners;
it does not grant a Verified badge. Flow Steward maintained integrations are
created and maintained by Flow Steward. They are not official extensions from,
or endorsed by, the integrated product's provider.

[`verified_extensions.json`](verified_extensions.json) selects tested integrations
by exact extension id, repository URL and release version, with a maintainer
reason. The maintainer has designated these 20 integrations as tested:

| Integration | Selected release |
| --- | --- |
| Shopify | 0.5.5 |
| MySQL | 1.3.12 |
| PostgreSQL | 1.4.14 |
| Google Workspace | 0.3.7 |
| Telegram | 1.3.5 |
| WhatsApp | 0.1.4 |
| Docling | 0.3.7 |
| Example Showcase | 1.2.8 |
| File Transfer | 0.3.10 |
| Generic IMAP | 0.2.5 |
| OpenRouter | 1.2.4 |
| Ollama | 1.2.4 |
| Outgoing Email | 0.3.5 |
| TypeSafe AI | 1.0.9 |
| Web Scraper | 0.1.29 |
| Image Processing | 0.2.9 |
| Discogs | 0.2.7 |
| Microsoft 365 | 0.2.7 |
| WordPress & WooCommerce | 1.2.6 |
| Gotenberg | 0.1.0 |

The configuration binds each selection to its exact repository and extension id;
it takes effect when that release is recorded and listed. This records that
selection, not a new live-test result or date. Every other release is unverified;
future versions require explicit review and selection. The index builder applies
current curation to historical records without changing their archive hashes,
source tags or immutable release records. Missing curation grants no badges;
malformed curation fails the build.

### Support in Flow Steward maintained extensions

New releases and submissions from `Flow-Steward` repositories must register a
**Support** page through `extension.yaml`'s `ui_manifest` and its `pages` list.
The page must have `page_id: support`, `title: Support` and
`project_scoped: false`, so administrators can reach it without a project.
Ship every referenced page and component in the archive. Inline markdown and
bundle-local component refs are supported; merely shipping a file called
`support.yaml` does not register a page.

The rendered markdown must contain both links to the extension's own repository:
`https://github.com/Flow-Steward/<repo>/issues/new/choose` and
`https://github.com/Flow-Steward/<repo>/issues`. Set `vendor.support_url` to that
repository's issues page or issue chooser (the host's root `support_url` alias
is also accepted). Enable GitHub Issues and maintain the
issue templates in the source repository; the archive validator checks the
registered content and exact destinations without making network requests.
See [`templates/single-extension/SUPPORT.md`](templates/single-extension/SUPPORT.md)
for a minimal contract and report guidance.

This first-party publication policy does not apply to unrelated external authors.
Previously recorded releases remain immutable and are rechecked for changed
archive bytes, not retrospectively rejected for this new Support policy.

### Reviewing categorization

Category filters describe function; capabilities describe host contracts. `ai`
does not imply `llm_provider`: TypeSafe JEV, image inference and vector retrieval
can belong to AI without registering models in Flow Steward. Keep capabilities
equal to the release's `features`; do not infer `query`, `dataset_connector`,
`notify` or `workflow_trigger` from a product name or a REST read operation.

Maintainers may correct a published release's categories in
[`category_overrides.json`](category_overrides.json), without rebuilding its
unchanged runtime or editing immutable `releases/` records. Each correction has
exactly `repository_url` (the source repository at `tree/v<version>`), `categories`
and a factual `reason`. It applies only while that exact source release is listed.
New releases use their own manifest again; authors should carry the reviewed
categories into `listing.categories`. Unknown categories, duplicate ids and
fields that could override capabilities or permissions fail the build.

The normal generator applies corrections every time, including scheduled runs.
[`docs/category-audit-2026-11-02.md`](docs/category-audit-2026-11-02.md) records the
review of all 35 releases and the boundaries behind their classification.

The catalog sets no `compatible_flow_steward` range: a manifest's
`runtime.compatibility.platform_min` is the extension host contract version, not
the Flow Steward product version the catalog range is compared with. The installer
still enforces `platform_min` itself.

## Maintainers

### Dependency monitoring

The **Monitor extension dependencies** workflow checks published Flow-Steward
extensions daily, checks tagged source declarations and verified published binary inventories, and
opens catalog issues for newer stable versions and OSV vulnerability matches.
Shared findings are grouped; repeated runs do not duplicate issues. Each run
includes a dependency inventory and explicit coverage gaps. See
[dependency monitoring](docs/dependency-monitoring.md) for supported sources,
manual dry runs, limitations and issue handling.

```bash
pip install -r requirements.txt
python -m pytest -q scripts                                   # builder tests
python scripts/build_index.py --check --base origin/main --submitter <login>
python scripts/build_index.py --publish                       # what the hourly job runs
```

The pull request check runs the base branch's copy of `scripts/build_index.py`, so
a submission cannot change the check that judges it. The **Publish new releases**
workflow needs `contents: write` for the built-in `GITHUB_TOKEN`
(Settings → Actions → General → Workflow permissions). If `main` is protected,
allow GitHub Actions to push to it.

Point Flow Steward at the catalog with

```
FS_EXTENSION_CATALOG_URL=https://raw.githubusercontent.com/<owner>/<repo>/main/index.json
```

The format is `extension_catalog/v1`, documented in Flow Steward's
`docs/catalogs/static-catalog-contracts.md`.

## Automatic first-party releases

First-party extensions build, validate and publish release ZIPs through GitHub Actions.
See [the release commands and CI contract](docs/automatic-extension-releases.md).
