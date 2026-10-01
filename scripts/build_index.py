#!/usr/bin/env python3
"""Build the Flow Steward extension catalog from authors' own GitHub repositories.

An extension lives in its author's repository. To list it, the author adds one
file to this catalog, ``extensions/<extension_id>.yaml``::

    repository: https://github.com/<owner>/<repo>

and publishes versions as GitHub Releases in that repository: tag ``v1.2.0``
with the asset ``<extension_id>-1.2.0.zip``. Nothing else is written by hand:

* a pull request adding an entry is checked here: the entry, the submitter's
  ownership of the repository, and that the latest release is installable;
* on a schedule, every entry's new releases are downloaded, checked, and
  recorded once in ``releases/<extension_id>/<version>.json`` with the asset's
  URL, size and SHA-256 — the digest Flow Steward verifies before installing;
* the listed asset of each extension is fetched again; one whose bytes changed
  is withdrawn and the previous release is listed instead;
* ``index.json`` is rebuilt from those records.

    python scripts/build_index.py                     # write index.json from releases/
    python scripts/build_index.py --check --base origin/main --submitter <login>
                                                      # validate a pull request
    python scripts/build_index.py --publish           # record new releases, then write index.json

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
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

import yaml

# FS_CATALOG_ROOT lets the pull request check run the base branch's copy of this
# script against the submitted tree, so a submission cannot rewrite its own check.
ROOT = Path(os.environ.get("FS_CATALOG_ROOT") or Path(__file__).resolve().parent.parent).resolve()
ENTRIES_DIR = "extensions"
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
_REPOSITORY = re.compile(r"^https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)$")

# Directories the product bundler leaves out; an archive carrying them is
# harmless, so they are ignored rather than refused.
_IGNORED_DIRECTORIES = frozenset(
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

# A scalar under one of these keys in a manifest or config file is a leaked secret.
_SECRET_KEYS = re.compile(r"(password|secret|api[_-]?key|access[_-]?token|private[_-]?key)$", re.I)
_PRIVATE_KEY_BLOCK = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_SECRET_FILE_NAMES = re.compile(r"^(\.env(\..*)?|id_rsa|id_ed25519|.*\.pem|.*\.key|.*\.p12|.*\.pfx)$")
_STRUCTURED_SUFFIXES = {".yaml", ".yml", ".json"}
_SYMLINK_MODE = 0o120000

# Runtime targets Flow Steward installs native packages for, with the ELF
# e_machine value of each (core/infrastructure/extension_runtime/native_package.py).
RUNTIME_TARGETS = {"linux-amd64": 62, "linux-arm64": 183}
DEFAULT_TARGET = "linux-amd64"
PACKAGE_METADATA = ".fs-package.yaml"


class CatalogError(Exception):
    """Something cannot be published; the message lists every problem found."""


@dataclass(frozen=True)
class Entry:
    """One ``extensions/<extension_id>.yaml`` file."""

    extension_id: str
    repository: str
    owner: str
    repo: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"


class GitHub(Protocol):
    """The few GitHub calls the catalog makes; tests substitute a fake."""

    def repository(self, slug: str) -> dict[str, Any]: ...

    def releases(self, slug: str) -> list[dict[str, Any]]: ...

    def is_public_member(self, org: str, login: str) -> bool: ...

    def download(self, url: str, *, max_bytes: int) -> bytes: ...


# ---------------------------------------------------------------------------
# GitHub over HTTPS
# ---------------------------------------------------------------------------


class GitHubApi:
    """GitHub REST client; GITHUB_TOKEN (set in Actions) raises the rate limit."""

    def __init__(self, token: str = "") -> None:
        self._token = token or os.environ.get("GITHUB_TOKEN", "") or os.environ.get("GH_TOKEN", "")

    def _open(self, url: str, *, accept: str = "application/vnd.github+json"):
        if not url.startswith("https://"):
            raise CatalogError(f"{url}: only https URLs are fetched")
        request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "flow-steward-catalog"})
        if self._token and url.startswith("https://api.github.com/"):
            request.add_header("Authorization", f"Bearer {self._token}")
        return urllib.request.urlopen(request, timeout=60)  # noqa: S310 - https only

    def _json(self, path: str) -> Any:
        with self._open(f"https://api.github.com{path}") as response:
            return json.load(response)

    def repository(self, slug: str) -> dict[str, Any]:
        try:
            return self._json(f"/repos/{slug}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise CatalogError(f"https://github.com/{slug} is not a public repository") from exc
            raise

    def releases(self, slug: str) -> list[dict[str, Any]]:
        return self._json(f"/repos/{slug}/releases?per_page=100")

    def is_public_member(self, org: str, login: str) -> bool:
        try:
            with self._open(f"https://api.github.com/orgs/{org}/public_members/{login}") as response:
                return response.status == 204
        except urllib.error.HTTPError:
            return False

    def download(self, url: str, *, max_bytes: int) -> bytes:
        with self._open(url, accept="application/octet-stream") as response:
            data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise CatalogError(f"{url}: larger than {max_bytes} bytes")
        return data


# ---------------------------------------------------------------------------
# small helpers
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


def _semver_key(version: str) -> tuple[int, int, int, int, str]:
    core, _, pre = version.partition("-")
    major, minor, patch = (int(part) for part in core.split("."))
    # A release sorts after its pre-releases.
    return (major, minor, patch, 0 if pre else 1, pre)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _json_file(name: str, default: Any) -> Any:
    path = ROOT / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


# ---------------------------------------------------------------------------
# catalog entries
# ---------------------------------------------------------------------------


def parse_entry(extension_id: str, text: str) -> Entry:
    where = f"{ENTRIES_DIR}/{extension_id}.yaml"
    if not _EXTENSION_ID.match(extension_id):
        raise CatalogError(
            f"{where}: name the file after a lowercase dotted extension_id such as acme.crm-sync"
        )
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CatalogError(f"{where}: not valid YAML ({exc})") from exc
    if not isinstance(data, dict) or set(data) != {"repository"}:
        raise CatalogError(f"{where}: must contain exactly one key, repository")
    repository = _text(data["repository"]).rstrip("/").removesuffix(".git")
    match = _REPOSITORY.match(repository)
    if not match:
        raise CatalogError(f"{where}: repository must look like https://github.com/<owner>/<repo>")
    return Entry(extension_id=extension_id, repository=repository, owner=match.group(1), repo=match.group(2))


def load_entries() -> dict[str, Entry]:
    base = ROOT / ENTRIES_DIR
    entries: dict[str, Entry] = {}
    problems: list[str] = []
    for path in sorted(base.glob("*.yaml")) if base.is_dir() else []:
        try:
            entry = parse_entry(path.stem, path.read_text(encoding="utf-8"))
        except CatalogError as exc:
            problems.append(str(exc))
            continue
        # One repository may publish several extensions (a family of variants
        # built from one codebase); each still has its own entry, id and assets.
        entries[entry.extension_id] = entry
    if problems:
        raise CatalogError("\n".join(problems))
    return entries


def verified_publishers() -> dict[str, str]:
    """Reserved namespace (first part of an id) -> the GitHub owner allowed to use it."""
    return {str(k): str(v) for k, v in _json_file(VERIFIED_PUBLISHERS_FILE, {}).items()}


def namespace_problem(entry: Entry, publishers: dict[str, str]) -> str:
    namespace = entry.extension_id.split(".", 1)[0]
    owner = publishers.get(namespace)
    if owner and owner.lower() != entry.owner.lower():
        return f"the '{namespace}.' namespace is reserved for github.com/{owner}"
    return ""


def can_submit(entry: Entry, submitter: str, github: GitHub) -> bool:
    """The submitter owns the repository, or is a public member of the owning organization."""
    if submitter.lower() == entry.owner.lower():
        return True
    owner = github.repository(entry.slug).get("owner") or {}
    return owner.get("type") == "Organization" and github.is_public_member(entry.owner, submitter)


# ---------------------------------------------------------------------------
# one release archive
# ---------------------------------------------------------------------------


def _archive_files(
    archive: zipfile.ZipFile, top: str, problems: list[str], *, target: str = ""
) -> dict[str, zipfile.ZipInfo]:
    """Files under the one top folder, minus ignored directories; problems are appended.

    ``bin/`` is accepted only in a per-target archive, and only for its own target.
    """
    files: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        if info.filename.startswith("/") or ".." in path.parts:
            problems.append(f"{info.filename}: unsafe path")
            continue
        if info.is_dir():
            continue
        if path.parts[0] != top or len(path.parts) < 2:
            problems.append(f"{info.filename}: every file must be inside the top folder '{top}/'")
            continue
        relative = PurePosixPath(*path.parts[1:])
        if any(part in _IGNORED_DIRECTORIES for part in relative.parts):
            continue
        total += info.file_size
        if (info.external_attr >> 16) & 0o170000 == _SYMLINK_MODE:
            problems.append(f"{relative}: symbolic links cannot be published")
        elif relative.parts[0] == "bin" and not target:
            problems.append(
                f"{relative}: a native executable needs one archive per runtime target "
                f"({', '.join(asset_name('<id>', '<version>', t) for t in RUNTIME_TARGETS)})"
            )
        elif relative.parts[0] == "bin" and relative.parts[1:2] != (target,):
            problems.append(f"{relative}: the {target} archive may only carry bin/{target}/")
        elif _SECRET_FILE_NAMES.match(relative.name):
            problems.append(f"{relative}: key and environment files must not be published")
        else:
            files[relative.as_posix()] = info
    if total > MAX_UNCOMPRESSED_BYTES:
        problems.append(f"unpacks to {total} bytes; the ceiling is {MAX_UNCOMPRESSED_BYTES}")
    return files


def _content_problems(contents: dict[str, bytes]) -> list[str]:
    problems: list[str] = []
    for name, blob in contents.items():
        if _PRIVATE_KEY_BLOCK.search(blob):
            problems.append(f"{name}: contains a private key")
        if PurePosixPath(name).suffix in _STRUCTURED_SUFFIXES:
            try:
                parsed = json.loads(blob) if name.endswith(".json") else yaml.safe_load(blob.decode("utf-8"))
            except (ValueError, yaml.YAMLError, UnicodeDecodeError):
                continue
            problems.extend(f"{name}: '{key}' must not carry secrets" for key in _secret_values(parsed))
    return problems


def _descriptor_problems(contents: dict[str, bytes], *, extension_id: str, version: str) -> list[str]:
    """The installer refuses a descriptor that disagrees with extension.yaml."""
    if DESCRIPTOR not in contents:
        return []
    try:
        descriptor = yaml.safe_load(contents[DESCRIPTOR].decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError):
        descriptor = None
    if not isinstance(descriptor, dict):
        return [f"{DESCRIPTOR} must be a YAML mapping"]
    problems: list[str] = []
    if _text(descriptor.get("extension_id")) != extension_id:
        problems.append(f"{DESCRIPTOR}: extension_id must be '{extension_id}'")
    release_version = _text(descriptor.get("release_version"))
    if release_version and release_version != version:
        problems.append(f"{DESCRIPTOR}: release_version {release_version} must match version {version}")
    return problems


def _elf_machine(blob: bytes) -> int | None:
    if len(blob) < 20 or blob[:4] != b"\x7fELF" or blob[4] != 2:
        return None
    return int.from_bytes(blob[18:20], "little" if blob[5] == 1 else "big")


def _native_problems(
    files: dict[str, zipfile.ZipInfo], contents: dict[str, bytes], *, target: str
) -> list[str]:
    """What Flow Steward's native package check would refuse in a per-target archive."""
    if PACKAGE_METADATA not in contents:
        return [f"{PACKAGE_METADATA} is missing; build with `flow-steward extensions bundle --runtime-target {target}`"]
    try:
        metadata = yaml.safe_load(contents[PACKAGE_METADATA].decode("utf-8")) or {}
    except (yaml.YAMLError, UnicodeDecodeError):
        metadata = None
    if not isinstance(metadata, dict):
        return [f"{PACKAGE_METADATA} must be a YAML mapping"]
    problems: list[str] = []
    if _text(metadata.get("runtime_target")) != target:
        problems.append(f"{PACKAGE_METADATA} declares runtime_target '{metadata.get('runtime_target')}', not {target}")
    native = metadata.get("native_executable") if isinstance(metadata.get("native_executable"), dict) else {}
    path = _text(native.get("path"))
    if PurePosixPath(path).parts[:2] != ("bin", target) or path not in contents:
        return problems + [f"{PACKAGE_METADATA}: native_executable.path must name a file in bin/{target}/"]
    executables = [name for name, blob in contents.items() if _elf_machine(blob[:20]) is not None]
    if executables != [path]:
        problems.append(f"exactly one native executable may ship, the declared {path} (found {executables})")
    blob = contents[path]
    if hashlib.sha256(blob).hexdigest() != _text(native.get("sha256")).lower():
        problems.append(f"{path}: SHA-256 differs from {PACKAGE_METADATA}")
    if _elf_machine(blob) != RUNTIME_TARGETS[target]:
        problems.append(f"{path}: is not a {target} ELF64 executable")
    if not (files[path].external_attr >> 16) & 0o111:
        problems.append(f"{path}: must be executable (mode +x in the archive)")
    return problems


def inspect_archive(
    data: bytes,
    *,
    entry: Entry,
    version: str,
    categories: set[str],
    publishers: dict[str, str],
    target: str = "",
) -> dict[str, Any]:
    """Check one release ZIP and derive its catalog fields; raises with every problem."""
    where = f"{entry.extension_id} {version}" + (f" ({target})" if target else "")
    if len(data) > MAX_ZIP_BYTES:
        raise CatalogError(f"{where}: the archive is {len(data)} bytes; the ceiling is {MAX_ZIP_BYTES}")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise CatalogError(f"{where}: not a ZIP archive") from exc
    top = folder_name(entry.extension_id)
    problems: list[str] = []
    with archive:
        files = _archive_files(archive, top, problems, target=target)
        if MANIFEST not in files:
            problems.append(f"add {MANIFEST} at the root of the '{top}/' folder")
            raise CatalogError("\n".join(f"{where}: {problem}" for problem in problems))
        if files[MANIFEST].file_size > MAX_MANIFEST_BYTES:
            raise CatalogError(f"{where}: {MANIFEST} is larger than {MAX_MANIFEST_BYTES} bytes")
        contents = {name: archive.read(info) for name, info in files.items()}
    # A native executable is not text; scanning it for secrets is noise.
    problems.extend(
        _content_problems({n: b for n, b in contents.items() if not n.startswith("bin/")})
    )
    if target:
        problems.extend(_native_problems(files, contents, target=target))

    try:
        manifest = yaml.safe_load(contents[MANIFEST].decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise CatalogError(f"{where}: {MANIFEST} is not valid YAML ({exc})") from exc
    if not isinstance(manifest, dict):
        raise CatalogError(f"{where}: {MANIFEST} must be a mapping")

    listing = manifest.get("listing") if isinstance(manifest.get("listing"), dict) else {}
    name = _text(manifest.get("display_name"))
    description = _text(listing.get("description")) or _text(manifest.get("description"))
    summary = _text(listing.get("summary")) or _summary(description)
    category = _text(listing.get("category"))
    declared_id = _text(manifest.get("extension_id"))
    declared_version = _text(manifest.get("version"))
    if declared_id != entry.extension_id:
        problems.append(f"{MANIFEST} declares extension_id '{declared_id}', not '{entry.extension_id}'")
    if declared_version != version:
        problems.append(f"{MANIFEST} declares version '{declared_version}' but the release tag is v{version}")
    if not name or name == entry.extension_id:
        problems.append("display_name must be a readable title, not the extension id")
    if len(description) < MIN_DESCRIPTION_CHARS:
        problems.append(f"description must be at least {MIN_DESCRIPTION_CHARS} characters")
    if len(summary) > MAX_SUMMARY_CHARS:
        problems.append(f"listing.summary must be at most {MAX_SUMMARY_CHARS} characters")
    if category not in categories:
        problems.append(f"set listing.category to one of: {', '.join(sorted(categories))} (got '{category}')")
    problems.extend(_descriptor_problems(contents, extension_id=entry.extension_id, version=version))
    if problems:
        raise CatalogError("\n".join(f"{where}: {problem}" for problem in problems))

    namespace = entry.extension_id.split(".", 1)[0]
    verified = publishers.get(namespace, "").lower() == entry.owner.lower()
    # No compatible_flow_steward: the manifest's runtime.compatibility.platform_min is
    # the extension host contract version, not the product version Flow Steward
    # compares this range against. The installer still enforces platform_min itself.
    return {
        "extension_id": entry.extension_id,
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
        "verification_status": "verified" if verified else "unverified",
    }


# ---------------------------------------------------------------------------
# releases
# ---------------------------------------------------------------------------


def asset_name(extension_id: str, version: str, target: str = "") -> str:
    """The product bundler's file name: ``<id>-<version>[-<target>].zip``."""
    return f"{extension_id}-{version}-{target}.zip" if target else f"{extension_id}-{version}.zip"


def release_candidates(releases: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """(version, release) for published SemVer releases, oldest first."""
    found: dict[str, dict[str, Any]] = {}
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        version = _text(release.get("tag_name")).removeprefix("v")
        if _SEMVER.match(version):
            found.setdefault(version, release)
    return sorted(found.items(), key=lambda pair: _semver_key(pair[0]))


def fetch_release(
    entry: Entry,
    version: str,
    release: dict[str, Any],
    *,
    github: GitHub,
    categories: set[str],
    publishers: dict[str, str],
) -> dict[str, Any]:
    """Download, check and describe one release; returns its record.

    A release carries either one portable archive or one archive per runtime
    target. Per-target releases must include linux-amd64: the top-level
    ``release_zip_*`` fields name it for products that predate ``release_targets``.
    """
    assets = {_text(a.get("name")): a for a in release.get("assets") or []}
    tag = _text(release.get("tag_name"))
    portable = asset_name(entry.extension_id, version)
    targeted = {t: asset_name(entry.extension_id, version, t) for t in RUNTIME_TARGETS}
    present = [t for t, name in targeted.items() if name in assets]
    if portable in assets and present:
        raise CatalogError(f"{entry.extension_id} {version}: attach {portable} or per-target archives, not both")
    if not present and portable not in assets:
        raise CatalogError(f"{entry.extension_id} {version}: attach {portable} to the release {tag}")
    if present and DEFAULT_TARGET not in present:
        raise CatalogError(f"{entry.extension_id} {version}: per-target releases must include {targeted[DEFAULT_TARGET]}")

    artifacts: dict[str, dict[str, Any]] = {}
    item: dict[str, Any] = {}
    for target in present or [""]:
        url = _text(assets[targeted[target] if target else portable].get("browser_download_url"))
        data = github.download(url, max_bytes=MAX_ZIP_BYTES)
        item = inspect_archive(
            data, entry=entry, version=version, categories=categories, publishers=publishers, target=target
        )
        artifacts[target] = {
            "release_zip_url": url,
            "release_zip_bytes": len(data),
            "release_zip_sha256": hashlib.sha256(data).hexdigest(),
        }
    item.update({"repository_url": f"{entry.repository}/tree/{tag}", **artifacts[DEFAULT_TARGET if present else ""]})
    if present:
        item["release_targets"] = {t: artifacts[t] for t in sorted(artifacts)}
    return {
        "extension_id": entry.extension_id,
        "version": version,
        "repository": entry.repository,
        "tag": tag,
        "published_at": _now(),
        "item": item,
    }


def record_path(extension_id: str, version: str) -> Path:
    return ROOT / RELEASES_DIR / extension_id / f"{version}.json"


def write_record(record: dict[str, Any]) -> str:
    path = record_path(record["extension_id"], record["version"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path.relative_to(ROOT).as_posix()


def load_records() -> dict[str, dict[str, dict[str, Any]]]:
    """extension_id -> version -> release record."""
    records: dict[str, dict[str, dict[str, Any]]] = {}
    base = ROOT / RELEASES_DIR
    for path in sorted(base.glob("*/*.json")) if base.is_dir() else []:
        record = json.loads(path.read_text(encoding="utf-8"))
        records.setdefault(record["extension_id"], {})[record["version"]] = record
    return records


def listed_record(versions: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """The newest recorded release that was not withdrawn."""
    live = [version for version, record in versions.items() if not record.get("withdrawn")]
    return versions[max(live, key=_semver_key)] if live else None


@dataclass
class PublishReport:
    recorded: list[str]
    withdrawn: list[str]
    problems: list[str]


def _recheck(entry: Entry, versions: dict[str, dict[str, Any]], github: GitHub, report: PublishReport) -> None:
    """Withdraw the listed release when its served bytes no longer match the record."""
    listed = listed_record(versions)
    if listed is None or listed.get("repository") != entry.repository:
        return
    item = listed["item"]
    artifacts = list((item.get("release_targets") or {}).values()) or [item]
    for artifact in artifacts:
        try:
            served = github.download(artifact["release_zip_url"], max_bytes=MAX_ZIP_BYTES)
        except (CatalogError, OSError) as exc:
            report.problems.append(f"{entry.extension_id} {listed['version']}: could not re-check ({exc})")
            return
        if hashlib.sha256(served).hexdigest() != artifact["release_zip_sha256"]:
            listed["withdrawn"] = (
                f"{artifact['release_zip_url']} changed after it was recorded ({_now()})"
            )
            report.withdrawn.append(write_record(listed))
            return


def publish(*, github: GitHub) -> PublishReport:
    """Record every entry's new releases, and withdraw listed assets whose bytes changed.

    One author's broken release never blocks another's: problems are collected
    and reported, and that release is simply not recorded.
    """
    entries = load_entries()
    records = load_records()
    categories = set(_json_file(CATEGORIES_FILE, []))
    publishers = verified_publishers()
    report = PublishReport(recorded=[], withdrawn=[], problems=[])

    for entry in entries.values():
        reserved = namespace_problem(entry, publishers)
        if reserved:
            report.problems.append(f"{entry.extension_id}: {reserved}")
            continue
        known = records.get(entry.extension_id, {})
        _recheck(entry, known, github, report)
        try:
            candidates = release_candidates(github.releases(entry.slug))
        except (CatalogError, OSError) as exc:
            report.problems.append(f"{entry.extension_id}: could not list releases ({exc})")
            continue
        highest = max(known, key=_semver_key) if known else ""
        new = [
            (version, release)
            for version, release in candidates
            if not highest or _semver_key(version) > _semver_key(highest)
        ]
        if not known:
            # A new entry starts from its latest release; older ones were never listed.
            new = new[-1:]
        for version, release in new:
            try:
                record = fetch_release(
                    entry, version, release, github=github, categories=categories, publishers=publishers
                )
            except (CatalogError, OSError) as exc:
                report.problems.append(str(exc))
                continue
            report.recorded.append(write_record(record))
    return report


# ---------------------------------------------------------------------------
# the index
# ---------------------------------------------------------------------------


def build_index() -> dict[str, Any]:
    """The newest recorded, not withdrawn release of each extension.

    An extension whose entry was removed stays listed as ``deprecated``, so
    existing installs still see where they came from.
    """
    records = load_records()
    base = ROOT / ENTRIES_DIR
    present = {path.stem for path in base.glob("*.yaml")} if base.is_dir() else set()
    items: list[dict[str, Any]] = []
    newest = ""
    for extension_id, versions in records.items():
        listed = listed_record(versions)
        if listed is None:
            continue
        item = dict(listed["item"])
        if extension_id not in present:
            item["publication_status"] = "deprecated"
        items.append(item)
        newest = max(newest, listed["published_at"])
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


# ---------------------------------------------------------------------------
# pull requests
# ---------------------------------------------------------------------------


def changed_paths(base: str) -> list[tuple[str, str]]:
    """(status, path) of every file a pull request changes."""
    out = _git("diff", "--name-status", "--no-renames", f"{base}...HEAD")
    pairs: list[tuple[str, str]] = []
    for line in out.splitlines():
        if line.strip():
            status, path = line.split("\t", 1)
            pairs.append((status, path))
    return pairs


def _check_new_entry(entry: Entry, *, submitter: str, github: GitHub, categories: set[str], publishers: dict[str, str]) -> str:
    """Why a new entry cannot be listed; empty when it can."""
    reserved = namespace_problem(entry, publishers)
    if reserved:
        return reserved
    if not can_submit(entry, submitter, github):
        return (
            f"@{submitter} does not own {entry.repository}; submit from the owner's account "
            "or as a public member of the owning organization"
        )
    candidates = release_candidates(github.releases(entry.slug))
    if not candidates:
        return (
            f"{entry.repository} has no release yet; publish tag v<version> "
            f"with {asset_name(entry.extension_id, '<version>')}"
        )
    version, release = candidates[-1]
    fetch_release(entry, version, release, github=github, categories=categories, publishers=publishers)
    return ""


def check_pull_request(*, base: str, submitter: str, github: GitHub) -> list[str]:
    """Problems with a pull request; empty means it can be merged."""
    try:
        entries = load_entries()
    except CatalogError as exc:
        return [str(exc)]
    publishers = verified_publishers()
    categories = set(_json_file(CATEGORIES_FILE, []))
    problems: list[str] = []
    for status, path in changed_paths(base):
        if path == INDEX_FILE or path.startswith(f"{RELEASES_DIR}/"):
            problems.append(f"{path}: written by the publish job; do not edit it")
            continue
        entry = entries.get(PurePosixPath(path).stem) if path.startswith(f"{ENTRIES_DIR}/") else None
        if entry is None or status == "D":
            continue
        if status == "M":
            before = parse_entry(entry.extension_id, _git("show", f"{base}:{path}"))
            if before.repository != entry.repository:
                problems.append(f"{path}: moving a listed extension to another repository needs a maintainer")
            continue
        try:
            problem = _check_new_entry(
                entry, submitter=submitter, github=github, categories=categories, publishers=publishers
            )
        except (CatalogError, OSError) as exc:
            problem = str(exc)
        if problem:
            problems.append(f"{path}: {problem}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate a pull request")
    mode.add_argument("--publish", action="store_true", help="record new releases, then write the index")
    parser.add_argument("--base", help="git ref the pull request targets")
    parser.add_argument("--submitter", help="GitHub login that opened the pull request")
    args = parser.parse_args(argv)
    github = GitHubApi()
    try:
        if args.check:
            if not args.base or not args.submitter:
                parser.error("--check needs --base and --submitter")
            problems = check_pull_request(base=args.base, submitter=args.submitter, github=github)
            if problems:
                raise CatalogError("\n".join(problems))
            print("Catalog OK.")
            return 0
        if args.publish:
            report = publish(github=github)
            for path in report.recorded:
                print(f"Recorded {path}")
            for path in report.withdrawn:
                print(f"Withdrew {path}")
            for problem in report.problems:
                print(f"::warning::{problem}")
        text = render(build_index())
    except CatalogError as exc:
        print(f"Catalog check failed:\n{exc}", file=sys.stderr)
        return 1
    (ROOT / INDEX_FILE).write_text(text, encoding="utf-8")
    print(f"Wrote {INDEX_FILE} with {len(json.loads(text)['items'])} extensions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
