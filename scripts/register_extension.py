"""Register a public first-party release from its manifest and prove catalog delivery."""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path, PurePosixPath

import yaml

import build_index as builder

MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
_SHA = re.compile(r"[0-9a-f]{40}")
_CATALOG = "https://raw.githubusercontent.com/Flow-Steward/extensions"


def require(condition, message):
    if not condition:
        raise builder.CatalogError(message)


def repository_slug(value):
    require(isinstance(value, str), "repository must name a public Flow-Steward/ext-* repository")
    slug = value.removeprefix("https://github.com/").rstrip("/").removesuffix(".git")
    require(
        re.fullmatch(r"Flow-Steward/ext-[A-Za-z0-9][A-Za-z0-9._-]*", slug) is not None,
        "repository must name a public Flow-Steward/ext-* repository",
    )
    return slug


def manifest_name(value):
    require(isinstance(value, str), "manifest_path must be a relative extension.yaml path")
    path = PurePosixPath(value)
    require(
        re.fullmatch(r"[A-Za-z0-9._/-]+", value) is not None
        and not path.is_absolute()
        and not any(part in {".", ".."} for part in path.parts)
        and path.as_posix() == value
        and path.name == "extension.yaml",
        "manifest_path must be a safe relative extension.yaml path",
    )
    return value


class GitHubApi(builder.GitHubApi):
    def source_commit(self, repository, tag):
        reference = self._json(f"/repos/{repository}/git/ref/tags/{tag}")
        for _ in range(8):
            obj = reference.get("object", {}) if isinstance(reference, dict) else {}
            sha, kind = obj.get("sha"), obj.get("type")
            require(isinstance(sha, str) and _SHA.fullmatch(sha), "source tag has no valid commit")
            if kind == "commit":
                return sha
            require(kind == "tag", "source tag does not resolve to a commit")
            reference = self._json(f"/repos/{repository}/git/tags/{sha}")
        raise builder.CatalogError("source tag annotation chain is too deep")

    def manifest(self, repository, commit, path):
        return self.download(
            f"https://raw.githubusercontent.com/{repository}/{commit}/{path}",
            max_bytes=MAX_MANIFEST_BYTES,
        )


def _manifest(data):
    require(isinstance(data, bytes) and len(data) <= MAX_MANIFEST_BYTES, "manifest is missing or too large")
    try:
        result = yaml.safe_load(data)
    except (yaml.YAMLError, UnicodeError) as exc:
        raise builder.CatalogError("source extension.yaml is not valid YAML") from exc
    require(isinstance(result, dict), "source extension.yaml must be a mapping")
    return result


def _receipt(receipt):
    require(isinstance(receipt, dict) and receipt.get("schema_version") == 1, "invalid registration receipt")
    slug = repository_slug(receipt.get("repository"))
    extension_id, version = receipt.get("extension_id"), receipt.get("version")
    require(
        isinstance(extension_id, str) and extension_id == extension_id.strip(),
        "invalid receipt extension_id",
    )
    entry = builder.parse_entry(extension_id, f"repository: https://github.com/{slug}\n")
    require(isinstance(version, str) and _VERSION.fullmatch(version), "invalid receipt version")
    require(receipt.get("tag") == f"v{version}", "receipt tag does not match version")
    require(isinstance(receipt.get("source_sha"), str) and _SHA.fullmatch(receipt["source_sha"]),
            "invalid receipt source commit")
    return entry, version


def _same_release(record, expected):
    identity = ("extension_id", "version", "repository", "tag", "host_contract")
    assets = ("release_zip_url", "release_zip_bytes", "release_zip_sha256", "release_targets")
    return (
        isinstance(record, dict)
        and all(record.get(key) == expected.get(key) for key in identity)
        and isinstance(record.get("item"), dict)
        and all(record["item"].get(key) == expected["item"].get(key) for key in assets)
        and record.get("icon") == expected.get("icon")
    )


def register(repository, tag, manifest_path="extension.yaml", *, github=None):
    slug = repository_slug(repository)
    require(isinstance(tag, str) and tag.startswith("v") and _VERSION.fullmatch(tag[1:]),
            "tag must be a stable vMAJOR.MINOR.PATCH release")
    path = manifest_name(manifest_path)
    github = github or GitHubApi()
    metadata = github.repository(slug)
    require(
        isinstance(metadata, dict) and metadata.get("full_name") == slug and metadata.get("private") is False,
        "registration requires the expected public repository",
    )
    source_sha = github.source_commit(slug, tag)
    require(isinstance(source_sha, str) and _SHA.fullmatch(source_sha), "source tag has no valid commit")
    manifest = _manifest(github.manifest(slug, source_sha, path))
    extension_id, version = manifest.get("extension_id"), manifest.get("version")
    require(isinstance(extension_id, str) and extension_id == extension_id.strip(),
            "manifest extension_id must be a dotted identifier")
    require(isinstance(version, str) and _VERSION.fullmatch(version) and tag == f"v{version}",
            "manifest version must match the stable release tag")
    entry = builder.parse_entry(extension_id, f"repository: https://github.com/{slug}\n")
    publishers = builder.verified_publishers()
    problem = builder.namespace_problem(entry, publishers)
    require(not problem, problem)
    base = builder.ROOT / builder.ENTRIES_DIR
    require(not base.is_symlink() and (not base.exists() or base.is_dir()),
            "extensions must be a real directory")
    target = base / f"{extension_id}.yaml"
    require(not target.is_symlink(), f"{target.name}: registration cannot be a symbolic link")
    entries = builder.load_entries()
    existing = entries.get(extension_id)
    require(existing is None or existing.repository == entry.repository,
            f"{extension_id}: already registered to a different repository")
    releases = github.releases(slug)
    require(isinstance(releases, list), "could not read public releases")
    candidates = [
        release for release in releases
        if isinstance(release, dict) and release.get("tag_name") == tag
        and release.get("draft") is False and release.get("prerelease") is False
    ]
    require(len(candidates) == 1, f"{slug}: publish one public non-prerelease release {tag} first")
    record = builder.fetch_release(
        entry, version, candidates[0], github=github,
        categories=set(builder.category_labels()), publishers=publishers,
    )
    known = builder.record_path(extension_id, version)
    require(not known.is_symlink(), f"{extension_id}: unsafe existing release record")
    if known.exists():
        try:
            previous = json.loads(known.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise builder.CatalogError(f"{extension_id}: cannot validate existing release record") from exc
        require(_same_release(previous, record),
                f"{extension_id} {version}: existing release identity, bytes or icon changed")
    require(github.source_commit(slug, tag) == source_sha, "source tag changed during validation")
    changed = existing is None
    if changed:
        base.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("x", encoding="utf-8") as output:
                output.write(f"repository: {entry.repository}\n")
        except FileExistsError as exc:
            raise builder.CatalogError(f"{extension_id}: registration appeared concurrently; rerun safely") from exc
    return {
        "schema_version": 1, "extension_id": extension_id, "version": version,
        "repository": entry.repository, "tag": tag, "source_sha": source_sha,
        "registration_path": f"{builder.ENTRIES_DIR}/{extension_id}.yaml", "changed": changed,
    }


def verify_index(index, receipt, *, expected_item=None):
    entry, version = _receipt(receipt)
    require(
        isinstance(index, dict) and index.get("schema_version") == builder.SCHEMA_VERSION
        and isinstance(index.get("items"), list),
        "public catalog has an invalid extension_catalog/v1 schema",
    )
    items = [item for item in index["items"]
             if isinstance(item, dict) and item.get("extension_id") == entry.extension_id]
    require(len(items) == 1, f"public catalog must contain exactly one {entry.extension_id}")
    item = items[0]
    actual = item.get("version")
    require(isinstance(actual, str) and _VERSION.fullmatch(actual), "public catalog has an invalid version")
    require(builder._semver_key(actual) >= builder._semver_key(version),
            f"public catalog {entry.extension_id} is stale: expected at least {version}, found {actual}")
    require(item.get("publication_status") == "published",
            f"public catalog {entry.extension_id} is not actively published")
    require(item.get("repository_url") == f"{entry.repository}/tree/v{actual}",
            f"public catalog {entry.extension_id} points to a different repository or tag")
    urls = {
        f"{entry.repository}/releases/download/v{actual}/{builder.asset_name(entry.extension_id, actual, target)}"
        for target in ("", builder.DEFAULT_TARGET)
    }
    require(
        item.get("release_zip_url") in urls
        and isinstance(item.get("release_zip_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", item["release_zip_sha256"])
        and type(item.get("release_zip_bytes")) is int and item["release_zip_bytes"] > 0,
        f"public catalog {entry.extension_id} has invalid archive identity",
    )
    if expected_item is not None:
        require(item == expected_item, f"public catalog {entry.extension_id} differs from the validated item")
    return item


def verify_published(receipt, commit, expected_index, *, github=None, attempts=6, delay=5):
    entry, _ = _receipt(receipt)
    require(isinstance(commit, str) and _SHA.fullmatch(commit), "published commit must be a full SHA")
    require(type(attempts) is int and 1 <= attempts <= 12 and isinstance(delay, (int, float)) and 0 <= delay <= 30,
            "public catalog readback needs 1-12 attempts and a 0-30 second delay")
    expected = verify_index(expected_index, receipt)
    github = github or GitHubApi()
    require(github.source_commit(entry.slug, receipt["tag"]) == receipt["source_sha"],
            "source tag changed before public catalog verification")
    url = f"{_CATALOG}/{commit}/index.json"
    for attempt in range(attempts):
        try:
            data = github.download(url, max_bytes=builder.MAX_INDEX_BYTES)
        except OSError as exc:
            if attempt + 1 == attempts:
                raise builder.CatalogError(f"public catalog could not be read at published commit {commit}") from exc
            time.sleep(delay)
            continue
        try:
            index = json.loads(data)
        except (ValueError, UnicodeError) as exc:
            raise builder.CatalogError("public catalog returned invalid JSON") from exc
        return verify_index(index, receipt, expected_item=expected)
    raise builder.CatalogError("public catalog verification did not complete")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("register")
    prepare.add_argument("--repository", required=True)
    prepare.add_argument("--tag", required=True)
    prepare.add_argument("--manifest-path", default="extension.yaml")
    prepare.add_argument("--receipt", required=True, type=Path)
    for name in ("check", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--receipt", required=True, type=Path)
        command.add_argument("--expected-index", required=True, type=Path)
        if name == "verify":
            command.add_argument("--commit", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "register":
            result = register(args.repository, args.tag, args.manifest_path)
            args.receipt.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
        else:
            receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
            index = json.loads(args.expected_index.read_text(encoding="utf-8"))
            result = (verify_published(receipt, args.commit, index)
                      if args.command == "verify" else verify_index(index, receipt))
    except (builder.CatalogError, OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"Catalog registration refused: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
