# Flow Steward extension catalog

Extensions for [Flow Steward](https://github.com/vasily-piksis/agentic-team).
Flow Steward reads [`index.json`](index.json) and lists these extensions under
**Extensions → Marketplace**, where an administrator installs them in one click.

`index.json` and everything under `releases/` are generated. Never edit them by
hand: a GitHub Action builds them after every merge.

## Share an extension

1. Build and check the extension in Flow Steward as usual:
   `flow-steward extensions validate <extension_id> --root extensions`.
2. In `extension.yaml`, make sure it has:
   - a readable `display_name` and a `description` of at least 40 characters;
   - `listing.category`, one of [`categories.json`](categories.json);
   - optionally `listing.summary` (the card line; otherwise the first sentence of
     the description), `listing.tags` and `listing.setup_summary`.
3. Add the extension's source folder as `extensions/<folder>/`, where `<folder>` is
   the `extension_id` with dots and dashes replaced by `_`
   (`acme.crm-sync` → `extensions/acme_crm_sync/`).
4. Open a pull request. Reviewers read your source, and the **Validate submission**
   check tells you what to fix.

After the merge, the publish job zips the folder, attaches the ZIP to a GitHub
Release named `<extension_id>-v<version>`, and lists it in the catalog.

### What the check refuses

- a folder without `extension.yaml`, or one whose name does not match the id;
- a version that is not semantic (`1.0.0`), or not higher than the last release;
- files changed in a released version without raising `version`;
- a category that is not in the list;
- a value under a key such as `password`, `api_key` or `secret`, a private key,
  `.env` or key files;
- native per-platform payloads (`bin/`) — not supported by this catalog yet;
- an archive over 50 MB (150 MB unpacked), Flow Steward's own install ceiling;
- a pull request that edits `releases/` or `index.json`.

### Updating a published extension

Change the folder and raise `version` in `extension.yaml`. Every released version
keeps its GitHub Release, so anyone who installed it can still see what they run.
Deleting a folder keeps the extension listed as **deprecated**.

## What the catalog shows, and where it comes from

| Field | Source |
| --- | --- |
| Name, summary, description | `display_name`, `listing.summary`, `description` |
| Category | `listing.category` |
| Capabilities | `features` |
| Permissions | `required_scopes` |
| Setup | `listing.setup_summary` |
| Tags | `listing.tags` (kept for the future marketplace, not shown yet) |
| Documentation link | the folder at the commit the release was built from |
| Download URL, size, SHA-256 | the GitHub Release asset, recorded once in `releases/` |
| Verified | the publisher (first part of the id) is in [`verified_publishers.json`](verified_publishers.json) |

The catalog sets no `compatible_flow_steward` range: a manifest's
`runtime.compatibility.platform_min` is the extension host contract version, not
the Flow Steward product version the catalog range is compared with. The installer
still enforces `platform_min` itself.

## Maintainers

```bash
pip install -r requirements.txt
python -m pytest -q scripts                        # builder tests
python scripts/build_index.py --check --base origin/main
python scripts/build_index.py                      # rebuild index.json from releases/
```

The **Publish releases and index** workflow needs `contents: write` for the
built-in `GITHUB_TOKEN` (Settings → Actions → General → Workflow permissions). If
`main` is protected, allow GitHub Actions to push to it.

Point Flow Steward at the catalog with

```
FS_EXTENSION_CATALOG_URL=https://raw.githubusercontent.com/<owner>/<repo>/main/index.json
```

The format is `extension_catalog/v1`, documented in Flow Steward's
`docs/catalogs/static-catalog-contracts.md`.
