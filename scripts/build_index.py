#!/usr/bin/env python3
"""Build the Flow Steward extension catalog from extension source folders.

Authors add or update one folder under ``extensions/<folder>/`` holding a normal
Flow Steward extension (``extension.yaml`` at its root). Nothing else is written
by hand:

* every index field comes from the manifest, the folder, and git history;
* on merge, the publish job zips each new version once, uploads the ZIP as a
  GitHub Release asset, and records its URL, size and SHA-256 in
  ``releases/<extension_id>/<version>.json``;
* ``index.json`` is rebuilt from those release records.

    python scripts/build_index.py                     # write index.json from releases/
    python scripts/build_index.py --check --base origin/main
                                                      # validate a pull request
    python scripts/build_index.py --publish           # release new versions, then write index.json

The output follows ``extension_catalog/v1`` as Flow Steward validates it
(``core/application/extensions/extension_catalog.py``). Unknown fields are ignored
by Flow Steward, so fields added here must stay optional there.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
EXTENSIONS_DIR = "extensions"
RELEASES_DIR = "releases"
CATEGORIES_FILE = "categories.json"
VERIFIED_PUBLISHERS_FILE = "verified_publishers.json"
INDEX_FILE = "index.json"
MANIFEST = "extension.yaml"
DESCRIPTOR = "extension-descriptor.yaml"

SCHEMA_VERSION = "extension_catalog/v1"

# Flow Steward's own ceilings (core/infrastructure/static_catalog/settings.py and
# core/application/tooling/extensions/bundle_extension.py).
MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 150 * 1024 * 1024
MAX_MANIFEST_BYTES = 512 * 1024
MAX_INDEX_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 5000
MAX_SUMMARY_CHARS = 160
MIN_DESCRIPTION_CHARS = 40

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
# core/infrastructure/extension_runtime/package_identity.py
_EXTENSION_ID = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)

# The product bundler leaves these out of an archive; so does the catalog.
_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".fs-python",
        ".hypothesis",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "dev-wheels",
    }
)
_EXCLUDED_FILES = frozenset({".fs-extension-install.yaml", ".fs-package.yaml"})

# A scalar under one of these keys in a manifest or config file is a leaked secret.
_SECRET_KEYS = re.compile(r"(password|secret|api[_-]?key|access[_-]?token|private[_-]?key)$", re.I)
_PRIVATE_KEY_BLOCK = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_SECRET_FILE_NAMES = re.compile(r"^(\.env(\..*)?|id_rsa|id_ed25519|.*\.pem|.*\.key|.*\.p12|.*\.pfx)$")
_STRUCTURED_SUFFIXES = {".yaml", ".yml", ".json"}

# Fixed so a rebuild of the same files gives the same entries (not necessarily the
# same deflate bytes, which is why the release record, not a rebuild, owns the digest).
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class CatalogError(Exception):
    """One or more extensions cannot be published; the message lists every problem."""


@dataclass(frozen=True)
class Source:
    """One extension folder at HEAD, validated."""

    folder: str
    extension_id: str
    version: str
    item: dict[str, Any]
    files: tuple[str, ...]


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _git_ok(*args: str) -> bool:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True).returncode == 0


def _last_commit(path: str) -> str:
    return _git("log", "-1", "--format=%H", "--", path) or _git("rev-parse", "HEAD")


def _repository() -> str:
    """owner/name for URLs: GITHUB_REPOSITORY in Actions, else the origin remote."""
    env = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if env:
        return env
    url = _git("remote", "get-url", "origin")
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    if not match:
        raise CatalogError(f"cannot derive owner/name from remote '{url}'; set GITHUB_REPOSITORY")
    return match.group(1)


def _tracked_files(folder: str) -> list[str]:
    """Files git tracks in one extension folder, relative to that folder.

    Only tracked files ship: caches, virtualenvs and local builds an author has on
    disk never reach an archive, whatever their .gitignore says.
    """
    prefix = f"{EXTENSIONS_DIR}/{folder}/"
    out = _git("ls-files", "-z", "--", prefix)
    return sorted(path[len(prefix) :] for path in out.split("\0") if path.startswith(prefix))


# ---------------------------------------------------------------------------
# derivation from one extension folder
# ---------------------------------------------------------------------------


def _text(value: Any) -> str:
    return str(value or "").strip()


def _summary(description: str) -> str:
    first = re.split(r"(?<=[.!?])\s+|\n\s*\n", description.strip(), maxsplit=1)[0].strip()
    if len(first) <= MAX_SUMMARY_CHARS:
        return first
    return first[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"


def folder_name(extension_id: str) -> str:
    """The product's folder name for an id (package_identity.extension_folder_name)."""
    return extension_id.replace(".", "_").replace("-", "_")


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(_text(item) for item in value if _text(item)))


def _secret_values(node: Any, path: str = "") -> list[str]:
    leaks: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            if str(key).endswith("_names"):
                # `secret_names: {access_token: access_token}` names where a secret is
                # stored; the values are field names, not secrets.
                continue
            if _SECRET_KEYS.search(str(key)) and isinstance(value, str) and value.strip():
                if not value.strip().startswith(("${", "secret:", "{{")):
                    leaks.append(here)
            leaks.extend(_secret_values(value, here))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            leaks.extend(_secret_values(value, f"{path}[{index}]"))
    return leaks


def _shipped(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    return not any(part in _EXCLUDED_DIRECTORIES for part in parts) and parts[-1] not in _EXCLUDED_FILES


def _file_problems(folder_path: Path, files: list[str]) -> list[str]:
    problems: list[str] = []
    for relative in files:
        path = folder_path / relative
        parts = PurePosixPath(relative).parts
        if path.is_symlink():
            problems.append(f"{relative}: symbolic links cannot be published")
            continue
        if parts[0] == "bin":
            problems.append(
                f"{relative}: native per-platform payloads (bin/) are not accepted by this catalog yet"
            )
            continue
        if _SECRET_FILE_NAMES.match(parts[-1]):
            problems.append(f"{relative}: key and environment files must not be committed")
            continue
        data = path.read_bytes()
        if _PRIVATE_KEY_BLOCK.search(data):
            problems.append(f"{relative}: contains a private key")
        if path.suffix in _STRUCTURED_SUFFIXES:
            try:
                parsed = (
                    json.loads(data) if path.suffix == ".json" else yaml.safe_load(data.decode("utf-8"))
                )
            except (ValueError, yaml.YAMLError, UnicodeDecodeError):
                continue
            problems.extend(
                f"{relative}: '{key}' must not carry secrets" for key in _secret_values(parsed)
            )
    return problems


def _descriptor_problems(folder_path: Path, files: list[str], *, extension_id: str, version: str) -> list[str]:
    """The installer refuses a descriptor that disagrees with extension.yaml."""
    if DESCRIPTOR not in files:
        return []
    try:
        descriptor = yaml.safe_load((folder_path / DESCRIPTOR).read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        return [f"{DESCRIPTOR}: not valid YAML ({exc})"]
    if not isinstance(descriptor, dict):
        return [f"{DESCRIPTOR}: must be a mapping"]
    problems: list[str] = []
    if _text(descriptor.get("extension_id")) != extension_id:
        problems.append(f"{DESCRIPTOR}: extension_id must be '{extension_id}'")
    release_version = _text(descriptor.get("release_version"))
    if release_version and release_version != version:
        problems.append(
            f"{DESCRIPTOR}: release_version {release_version} must match version {version} "
            "in extension.yaml"
        )
    return problems


def derive_source(
    folder: str,
    files: list[str],
    *,
    categories: set[str],
    verified_publishers: set[str],
) -> Source:
    """Validate one extension folder and derive its catalog fields.

    Raises CatalogError listing every problem in the folder, so an author fixes
    them in one round.
    """
    where = f"{EXTENSIONS_DIR}/{folder}"
    folder_path = ROOT / EXTENSIONS_DIR / folder
    shipped = [relative for relative in files if _shipped(relative)]
    if MANIFEST not in shipped:
        raise CatalogError(f"{where}: add {MANIFEST} at the root of the folder")
    manifest_bytes = (folder_path / MANIFEST).read_bytes()
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise CatalogError(f"{where}/{MANIFEST}: larger than {MAX_MANIFEST_BYTES} bytes")
    try:
        manifest = yaml.safe_load(manifest_bytes.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise CatalogError(f"{where}/{MANIFEST}: not valid YAML ({exc})") from exc
    if not isinstance(manifest, dict):
        raise CatalogError(f"{where}/{MANIFEST}: must be a mapping")

    problems: list[str] = []
    extension_id = _text(manifest.get("extension_id"))
    version = _text(manifest.get("version"))
    name = _text(manifest.get("display_name"))
    listing = manifest.get("listing") if isinstance(manifest.get("listing"), dict) else {}
    description = _text(listing.get("description")) or _text(manifest.get("description"))
    summary = _text(listing.get("summary")) or _summary(description)
    category = _text(listing.get("category"))

    if not _EXTENSION_ID.match(extension_id):
        problems.append(
            "extension_id must be a lowercase dotted id such as 'acme.crm-sync' "
            f"(got '{extension_id}')"
        )
    elif folder != folder_name(extension_id):
        problems.append(f"the folder for '{extension_id}' must be named '{folder_name(extension_id)}'")
    if not _SEMVER.match(version):
        problems.append(f"version must be semantic, such as 1.0.0 (got '{version}')")
    if not name or name == extension_id:
        problems.append("display_name must be a readable title, not the extension id")
    if len(description) < MIN_DESCRIPTION_CHARS:
        problems.append(f"description must be at least {MIN_DESCRIPTION_CHARS} characters")
    if len(summary) > MAX_SUMMARY_CHARS:
        problems.append(f"listing.summary must be at most {MAX_SUMMARY_CHARS} characters")
    if not category:
        problems.append(f"set listing.category to one of: {', '.join(sorted(categories))}")
    elif category not in categories:
        problems.append(
            f"listing.category '{category}' is not a catalog category; "
            f"use one of: {', '.join(sorted(categories))}"
        )
    problems.extend(_descriptor_problems(folder_path, shipped, extension_id=extension_id, version=version))
    problems.extend(_file_problems(folder_path, shipped))
    if problems:
        raise CatalogError("\n".join(f"{where}: {problem}" for problem in problems))

    publisher = extension_id.split(".", 1)[0]
    item: dict[str, Any] = {
        "extension_id": extension_id,
        "version": version,
        "name": name,
        "summary": summary,
        "description": description,
        "categories": [category],
        "capabilities": _strings(manifest.get("features")),
        "permissions_summary": sorted(_strings(manifest.get("required_scopes"))),
        "setup_summary": _text(listing.get("setup_summary")),
        "tags": _strings(listing.get("tags")),
        "publication_status": "published",
        "verification_status": "verified" if publisher in verified_publishers else "unverified",
    }
    # No compatible_flow_steward: the manifest's runtime.compatibility.platform_min is
    # the extension host contract version, not the product version Flow Steward
    # compares this range against. The installer still enforces platform_min itself.
    return Source(folder=folder, extension_id=extension_id, version=version, item=item, files=tuple(shipped))


# ---------------------------------------------------------------------------
# archives and release records
# ---------------------------------------------------------------------------


def build_zip(source: Source) -> bytes:
    """The archive Flow Steward installs: one top folder holding the tracked files."""
    folder_path = ROOT / EXTENSIONS_DIR / source.folder
    buffer = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in source.files:
            data = (folder_path / relative).read_bytes()
            total += len(data)
            info = zipfile.ZipInfo(f"{source.folder}/{relative}", date_time=_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    payload = buffer.getvalue()
    if total > MAX_UNCOMPRESSED_BYTES:
        raise CatalogError(
            f"{EXTENSIONS_DIR}/{source.folder}: unpacks to {total} bytes; "
            f"the ceiling is {MAX_UNCOMPRESSED_BYTES}"
        )
    if len(payload) > MAX_ZIP_BYTES:
        raise CatalogError(
            f"{EXTENSIONS_DIR}/{source.folder}: the archive is {len(payload)} bytes; "
            f"the ceiling is {MAX_ZIP_BYTES}"
        )
    return payload


def release_tag(extension_id: str, version: str) -> str:
    return f"{extension_id}-v{version}"


def release_file_name(extension_id: str, version: str) -> str:
    return f"{extension_id}-{version}.zip"


def record_path(extension_id: str, version: str) -> Path:
    return ROOT / RELEASES_DIR / extension_id / f"{version}.json"


def load_records() -> dict[str, dict[str, dict[str, Any]]]:
    """extension_id -> version -> release record."""
    records: dict[str, dict[str, dict[str, Any]]] = {}
    base = ROOT / RELEASES_DIR
    if not base.is_dir():
        return records
    for path in sorted(base.glob("*/*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        records.setdefault(record["extension_id"], {})[record["version"]] = record
    return records


# Uploads one archive and returns the bytes that are actually served at the URL.
Uploader = Callable[[str, str, bytes, str], tuple[str, bytes]]


def github_release_uploader(repository: str) -> Uploader:
    """Create a GitHub Release per version with the `gh` CLI (GITHUB_TOKEN in Actions).

    When the tag already exists — an earlier run uploaded and then failed before
    committing the record — the served asset is downloaded and its bytes are what
    the record describes, so the index never names a digest nobody serves.
    """

    def upload(tag: str, file_name: str, payload: bytes, commit: str) -> tuple[str, bytes]:
        url = f"https://github.com/{repository}/releases/download/{tag}/{file_name}"
        with tempfile.TemporaryDirectory() as tmp:
            existing = subprocess.run(
                ["gh", "release", "view", tag, "--repo", repository], capture_output=True
            )
            if existing.returncode == 0:
                subprocess.run(
                    ["gh", "release", "download", tag, "--repo", repository,
                     "--pattern", file_name, "--dir", tmp],
                    check=True,
                )
                return url, (Path(tmp) / file_name).read_bytes()
            archive = Path(tmp) / file_name
            archive.write_bytes(payload)
            subprocess.run(
                ["gh", "release", "create", tag, str(archive), "--repo", repository,
                 "--target", commit, "--title", tag, "--notes", f"Built from {commit}."],
                check=True,
            )
            return url, payload

    return upload


# ---------------------------------------------------------------------------
# the whole catalog
# ---------------------------------------------------------------------------


def _semver_key(version: str) -> tuple[int, int, int, int, str]:
    core, _, pre = version.partition("-")
    major, minor, patch = (int(part) for part in core.split("."))
    return (major, minor, patch, 0 if pre else 1, pre)


def _json_list(name: str) -> set[str]:
    path = ROOT / name
    return set(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else set()


def load_sources() -> list[Source]:
    """Every extension folder at HEAD, validated; raises with every problem found."""
    categories = _json_list(CATEGORIES_FILE)
    verified = _json_list(VERIFIED_PUBLISHERS_FILE)
    base = ROOT / EXTENSIONS_DIR
    folders = sorted(path.name for path in base.iterdir() if path.is_dir()) if base.is_dir() else []
    problems: list[str] = []
    sources: list[Source] = []
    owners: dict[str, str] = {}
    for folder in folders:
        files = _tracked_files(folder)
        if not files:
            continue
        try:
            source = derive_source(folder, files, categories=categories, verified_publishers=verified)
            build_zip(source)
        except CatalogError as exc:
            problems.append(str(exc))
            continue
        if source.extension_id in owners:
            problems.append(
                f"{EXTENSIONS_DIR}/{folder}: '{source.extension_id}' is already published "
                f"from {EXTENSIONS_DIR}/{owners[source.extension_id]}"
            )
            continue
        owners[source.extension_id] = folder
        sources.append(source)
    if problems:
        raise CatalogError("\n".join(problems))
    return sources


def check_versions(sources: list[Source], records: dict[str, dict[str, dict[str, Any]]]) -> None:
    """A changed folder must raise its version; a released version never changes."""
    problems: list[str] = []
    for source in sources:
        released = records.get(source.extension_id, {})
        where = f"{EXTENSIONS_DIR}/{source.folder}"
        record = released.get(source.version)
        if record is not None:
            if not _git_ok("diff", "--quiet", record["commit"], "HEAD", "--", where):
                problems.append(
                    f"{where}: {source.extension_id} {source.version} is already released and "
                    "its files changed; raise version in extension.yaml"
                )
            continue
        newer = [v for v in released if _semver_key(v) >= _semver_key(source.version)]
        if newer:
            highest = max(newer, key=_semver_key)
            problems.append(
                f"{where}: version {source.version} must be higher than the released {highest}"
            )
    if problems:
        raise CatalogError("\n".join(problems))


def publish(*, repository: str, uploader: Uploader) -> list[str]:
    """Release every folder whose version has no record yet; returns the new record paths."""
    sources = load_sources()
    records = load_records()
    check_versions(sources, records)
    written: list[str] = []
    for source in sources:
        if source.version in records.get(source.extension_id, {}):
            continue
        commit = _last_commit(f"{EXTENSIONS_DIR}/{source.folder}")
        tag = release_tag(source.extension_id, source.version)
        url, served = uploader(
            tag, release_file_name(source.extension_id, source.version), build_zip(source), commit
        )
        record = {
            "extension_id": source.extension_id,
            "version": source.version,
            "folder": source.folder,
            "commit": commit,
            "published_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "item": {
                **source.item,
                "repository_url": f"https://github.com/{repository}/tree/{commit}/{EXTENSIONS_DIR}/{source.folder}",
                "release_zip_url": url,
                "release_zip_bytes": len(served),
                "release_zip_sha256": hashlib.sha256(served).hexdigest(),
            },
        }
        path = record_path(source.extension_id, source.version)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(path.relative_to(ROOT).as_posix())
    return written


def build_index() -> dict[str, Any]:
    """The index from release records: the newest release of each extension.

    An extension whose folder was removed stays listed as ``deprecated`` so
    existing installs still see where they came from.
    """
    records = load_records()
    base = ROOT / EXTENSIONS_DIR
    present = {path.name for path in base.iterdir() if path.is_dir()} if base.is_dir() else set()
    items: list[dict[str, Any]] = []
    newest = ""
    for extension_id, versions in records.items():
        latest = versions[max(versions, key=_semver_key)]
        item = dict(latest["item"])
        if latest["folder"] not in present:
            item["publication_status"] = "deprecated"
        items.append(item)
        newest = max(newest, latest["published_at"])
    if len(items) > MAX_ITEMS:
        raise CatalogError(f"the catalog would carry {len(items)} items; the ceiling is {MAX_ITEMS}")
    items.sort(key=lambda item: (item["name"].lower(), item["extension_id"]))
    digest = hashlib.sha256(json.dumps(items, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:8]
    published = newest or "1970-01-01T00:00:00Z"
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_revision": f"{published[:10]}.{digest}",
        "published_at": published,
        "items": items,
    }


def render(index: dict[str, Any]) -> str:
    text = json.dumps(index, indent=2, ensure_ascii=False) + "\n"
    if len(text.encode("utf-8")) > MAX_INDEX_BYTES:
        raise CatalogError(f"index.json would exceed {MAX_INDEX_BYTES} bytes")
    return text


def generated_file_changes(base: str) -> list[str]:
    """Generated files a pull request touches (only the publish job writes them)."""
    out = _git("diff", "--name-only", f"{base}...HEAD", "--", RELEASES_DIR, INDEX_FILE)
    return [line for line in out.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate without writing")
    mode.add_argument("--publish", action="store_true", help="release new versions, then write the index")
    parser.add_argument("--base", help="git ref a pull request targets")
    parser.add_argument("--repository", help="owner/name used in URLs")
    args = parser.parse_args(argv)
    try:
        if args.check:
            if args.base:
                touched = generated_file_changes(args.base)
                if touched:
                    raise CatalogError(
                        "\n".join(f"{path}: written by the publish job; do not edit it" for path in touched)
                    )
            sources = load_sources()
            check_versions(sources, load_records())
            print(f"Catalog OK: {len(sources)} extensions.")
            return 0
        if args.publish:
            repository = args.repository or _repository()
            for path in publish(repository=repository, uploader=github_release_uploader(repository)):
                print(f"Released {path}")
        text = render(build_index())
    except CatalogError as exc:
        print(f"Catalog check failed:\n{exc}", file=sys.stderr)
        return 1
    (ROOT / INDEX_FILE).write_text(text, encoding="utf-8")
    print(f"Wrote {INDEX_FILE} with {len(json.loads(text)['items'])} extensions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
