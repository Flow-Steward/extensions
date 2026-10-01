# Flow Steward extension catalog

Extensions for [Flow Steward](https://github.com/Flow-Steward/flow-steward-app).
Flow Steward reads [`index.json`](index.json) and lists these extensions under
**Extensions → Marketplace**, where an administrator installs them in one click.

Every extension lives in **its author's own GitHub repository**. This catalog
only holds a link to it, and publishes the author's releases automatically.
`index.json` and everything under `releases/` are generated; never edit them.

## Share an extension

1. Keep the extension in its own public GitHub repository with `extension.yaml`
   at the repository root. Check it with
   `flow-steward extensions validate <extension_id>`.
2. In `extension.yaml`, make sure it has:
   - a readable `display_name` and a `description` of at least 40 characters;
   - `listing.category`, one of [`categories.json`](categories.json);
   - optionally `listing.summary` (the card line; otherwise the first sentence of
     the description), `listing.tags` and `listing.setup_summary`.
3. Publish a release: tag `v<version>` (the same version as `extension.yaml`)
   with the asset `<extension_id>-<version>.zip`, whose files sit under one top
   folder named after the id with `.` and `-` replaced by `_`
   (`acme.crm-sync` → `acme_crm_sync/`). Copy
   [`templates/release-extension.yml`](templates/release-extension.yml) into your
   repository's `.github/workflows/` and it does this for every tag you push.
4. Open a pull request here adding one file, `extensions/<extension_id>.yaml`:

   ```yaml
   repository: https://github.com/<owner>/<repo>
   ```

   Open it from the repository owner's account, or as a public member of the
   owning organization. The **Validate submission** check downloads your latest
   release and tells you what to fix.

After the merge your latest release is listed within the hour.

### An extension with a native executable

The installer accepts one architecture per archive, so attach one per runtime
target instead of a single archive: `<extension_id>-<version>-linux-amd64.zip`
and `<extension_id>-<version>-linux-arm64.zip`, each built with
`flow-steward extensions bundle --runtime-target <target>` (only that target's
`bin/<target>/` and its `.fs-package.yaml`). `linux-amd64` is required. Flow
Steward installs the archive for the architecture it runs on.

### Several extensions from one repository

A repository may publish a family of extensions built from one codebase — one
per database, say. Each has its own entry file and id, and each release tag
carries every member's archives. See
[ext-data-connector-mcp-toolbox](https://github.com/Flow-Steward/ext-data-connector-mcp-toolbox)
for a worked example.

### New versions

Push a new tag in your repository. The catalog checks every listed repository
every hour and publishes each new release that passes the same checks — no pull
request needed. A release that fails is reported in the catalog's Actions log and
the previous version stays listed.

### What the checks refuse

- an entry that is not exactly `repository: https://github.com/<owner>/<repo>`;
- a submitter who does not own the repository;
- the `flowsteward.` namespace, which is reserved for github.com/Flow-Steward
  (see [`verified_publishers.json`](verified_publishers.json)). The catalog is
  where that is enforced: Flow Steward itself installs any id, from here or as an
  uploaded archive, as WordPress installs any plugin;
- a release whose `extension.yaml` names another id or version than the entry and
  the tag, or whose `extension-descriptor.yaml` disagrees with it;
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
release, before it installs anything. Every hour the catalog downloads the listed
asset again: if its bytes changed, that release is withdrawn and the previous one
is listed instead. Removing an entry keeps the extension listed as **deprecated**.

## What the catalog shows, and where it comes from

| Field | Source |
| --- | --- |
| Name, summary, description | `display_name`, `listing.summary`, `description` |
| Category | `listing.category` |
| Capabilities | `features` |
| Permissions | `required_scopes` |
| Setup | `listing.setup_summary` |
| Tags | `listing.tags` (kept for the future marketplace, not shown yet) |
| Documentation link | the repository at the release tag |
| Download URL, size, SHA-256 | the release asset, recorded once in `releases/` |
| Verified | the id's namespace is mapped to the repository owner in `verified_publishers.json` |

The catalog sets no `compatible_flow_steward` range: a manifest's
`runtime.compatibility.platform_min` is the extension host contract version, not
the Flow Steward product version the catalog range is compared with. The installer
still enforces `platform_min` itself.

## Maintainers

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
