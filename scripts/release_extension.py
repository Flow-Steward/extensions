#!/usr/bin/env python3
"""Prepare and build first-party releases; verify publication artifacts without source execution."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

import yaml

MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_UNPACKED_BYTES = 150 * 1024 * 1024
MAX_JSON_BYTES = 512 * 1024
TARGETS = ["linux-amd64", "linux-arm64"]
SEMVER = r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?"
EXCLUDED = {
    ".git",
    ".github",
    ".venv",
    "venv",
    ".fs-python",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".hypothesis",
    ".cache",
    "dev-wheels",
    "dist",
    "build",
    "logs",
    "storage",
    "node_modules",
}
PLAN = "release-plan.json"


class ReleaseError(Exception):
    """Invalid release input, failed source packaging or unsafe publication artifact."""


def _require(condition, message):
    if not condition:
        raise ReleaseError(message)


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _keys(value, allowed, required, where):
    _require(isinstance(value, dict), f"{where} must be an object")
    _require(not (set(value) - set(allowed)), f"{where} has unknown fields")
    _require(set(required) <= set(value), f"{where} is missing required fields")


def _relative(value):
    _require(
        isinstance(value, str) and value and "\\" not in value and "\x00" not in value,
        "invalid relative path",
    )
    path = PurePosixPath(value)
    _require(
        not path.is_absolute()
        and all(p not in {"", ".", ".."} for p in value.split("/")),
        "unsafe relative path",
    )
    return path


def _path(root, value, *, exists=False):
    relative = _relative(value)
    path = root.joinpath(*relative.parts)
    _require(
        all(
            not parent.is_symlink()
            for parent in [path, *path.parents]
            if parent != root.parent
        ),
        "symlink path is forbidden",
    )
    _require(path.resolve().is_relative_to(root.resolve()), "path escapes root")
    if exists:
        _require(path.exists(), f"missing required path: {value}")
    return path


def _json(path):
    _require(
        path.is_file() and not path.is_symlink(),
        f"expected regular JSON file: {path.name}",
    )
    raw = path.read_bytes()
    _require(len(raw) <= MAX_JSON_BYTES, "JSON input exceeds size limit")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ReleaseError(f"invalid JSON: {path.name}") from exc


def _yaml(data, where):
    _require(len(data) <= MAX_JSON_BYTES, f"{where} exceeds manifest size limit")
    try:
        value = yaml.safe_load(data)
    except (yaml.YAMLError, UnicodeDecodeError, ValueError) as exc:
        raise ReleaseError(f"invalid YAML: {where}") from exc
    _require(isinstance(value, dict), f"{where} must be an object")
    return value


def _identity(repository, tag):
    _require(
        isinstance(repository, str)
        and re.fullmatch(r"Flow-Steward/ext-[A-Za-z0-9][A-Za-z0-9._-]*", repository),
        "repository must be Flow-Steward/ext-*",
    )
    _require(
        isinstance(tag, str) and re.fullmatch("v" + SEMVER, tag),
        "tag must be v<semver>",
    )
    return tag[1:]


def _targets(value):
    _require(
        isinstance(value, list) and (value == [""] or value == TARGETS),
        "runtime_targets must be portable or both supported Linux targets",
    )
    return value


def _strings(value, where):
    _require(
        isinstance(value, list) and all(isinstance(v, str) and v for v in value),
        f"{where} must be a string list",
    )
    _require(len(value) == len(set(value)), f"{where} has duplicates")
    return value


def _release_url(url, repository):
    _require(isinstance(url, str), "payload URL must be a string")
    parsed = urllib.parse.urlsplit(url)
    _require(
        parsed.scheme == "https"
        and parsed.netloc == "github.com"
        and not parsed.query
        and not parsed.fragment,
        "payload URL must be an uncredentialed GitHub HTTPS release URL",
    )
    prefix = "/" + repository + "/releases/download/"
    _require(
        parsed.path.startswith(prefix),
        "payload must come from the same repository release",
    )
    rest = parsed.path[len(prefix) :].split("/")
    _require(
        len(rest) == 2
        and re.fullmatch("v" + SEMVER, rest[0])
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.zip", rest[1]),
        "invalid release asset URL",
    )
    return rest[0][1:]


def _restore_path(path, target):
    parts = _relative(path).parts
    valid = (
        path == "packages.txt"
        or (len(parts) == 2 and parts[0] == "wheels" and parts[1].endswith(".whl"))
        or (target and path == f"bin/{target}/toolbox")
    )
    _require(
        valid,
        "restore path must name declared runtime binary, wheel or packages.txt inventory",
    )


def validate_recipe(source_root, repository, tag, config):
    root = Path(source_root).resolve()
    version = _identity(repository, tag)
    data = _json(_path(root, str(config), exists=True))
    _keys(
        data,
        {
            "schema_version",
            "extension_id",
            "runtime_targets",
            "payload_sources",
            "package_script",
            "test_requirements",
            "test_paths",
            "additional_assets",
            "notes_file",
        },
        {"schema_version", "extension_id", "runtime_targets"},
        "recipe",
    )
    _require(
        type(data["schema_version"]) is int and data["schema_version"] == 1,
        "unsupported recipe schema_version",
    )
    extension_id = data["extension_id"]
    _require(
        isinstance(extension_id, str)
        and re.fullmatch(r"flowsteward\.[a-z0-9]+(?:[.-][a-z0-9]+)*", extension_id),
        "invalid first-party extension_id",
    )
    _targets(data["runtime_targets"])
    manifest = _yaml(
        _path(root, "extension.yaml", exists=True).read_bytes(), "extension.yaml"
    )
    _require(
        manifest.get("extension_id") == extension_id
        and manifest.get("version") == version,
        "tag/manifest identity mismatch",
    )
    descriptor_path = _path(root, "extension-descriptor.yaml")
    if descriptor_path.exists():
        descriptor = _yaml(descriptor_path.read_bytes(), "extension-descriptor.yaml")
        _require(
            descriptor.get("extension_id") == extension_id
            and descriptor.get("release_version") == version,
            "tag/descriptor identity mismatch",
        )
    for field in ["test_requirements", "test_paths", "additional_assets"]:
        data.setdefault(field, [])
        for value in _strings(data[field], field):
            path = _path(
                root,
                value.split("::", 1)[0] if field == "test_paths" else value,
                exists=True,
            )
            _require(
                path.is_file() or (field == "test_paths" and path.is_dir()),
                f"{field} requires regular files or test directories",
            )
    if "notes_file" in data:
        _require(
            isinstance(data["notes_file"], str)
            and data["notes_file"] in data["additional_assets"],
            "notes_file must reference an additional asset",
        )
    if "package_script" in data:
        _require(
            data["package_script"]
            in {"scripts/package_extension.py", ".github/scripts/package_extension.py"},
            "unsupported package_script",
        )
        _require(
            _path(root, data["package_script"], exists=True).is_file(),
            "package_script must be a regular file",
        )
    data.setdefault("payload_sources", [])
    _require(
        isinstance(data["payload_sources"], list) and len(data["payload_sources"]) <= 2,
        "payload_sources must contain at most two declared assets",
    )
    seen = set()
    for payload in data["payload_sources"]:
        _keys(
            payload,
            {"target", "url", "bytes", "sha256", "restore_paths"},
            {"target", "url", "bytes", "sha256", "restore_paths"},
            "payload source",
        )
        _require(
            payload["target"] in data["runtime_targets"]
            and payload["target"] not in seen,
            "payload source target mismatch or duplicate",
        )
        seen.add(payload["target"])
        _release_url(payload["url"], repository)
        _require(
            type(payload["bytes"]) is int and 0 < payload["bytes"] <= MAX_ZIP_BYTES,
            "payload byte size is invalid",
        )
        _require(
            isinstance(payload["sha256"], str)
            and re.fullmatch("[0-9a-f]{64}", payload["sha256"]),
            "payload SHA256 is invalid",
        )
        paths = _strings(payload["restore_paths"], "restore_paths")
        _require(paths, "restore_paths cannot be empty")
        for path in paths:
            _restore_path(path, payload["target"])
            _path(root, path)
    return data


class _ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        _require(
            parsed.scheme == "https"
            and parsed.hostname
            in {
                "github.com",
                "release-assets.githubusercontent.com",
                "objects.githubusercontent.com",
            }
            and not parsed.username
            and not parsed.password,
            "unsafe release asset redirect",
        )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download_payload(url, limit):
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _ReleaseRedirect()
    )
    request = urllib.request.Request(
        url, headers={"User-Agent": "Flow-Steward-release-ci/1"}
    )
    with opener.open(request, timeout=120) as response:
        return response.read(limit + 1)


def _archive(data, extension_id):
    top = extension_id.replace(".", "_").replace("-", "_")
    entries = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            _require(len(archive.infolist()) <= 10000, "too many ZIP entries")
            _require(
                sum(info.file_size for info in archive.infolist())
                <= MAX_UNPACKED_BYTES,
                "ZIP exceeds unpacked size limit",
            )
            for info in archive.infolist():
                path = _relative(info.filename.rstrip("/"))
                _require(
                    path.parts[0] == top and len(path.parts) >= 2,
                    "wrong ZIP top folder",
                )
                _require(
                    stat.S_IFMT(info.external_attr >> 16) != stat.S_IFLNK,
                    "ZIP symlink is forbidden",
                )
                _require(
                    not info.flag_bits & 1
                    and info.compress_type
                    in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED},
                    "unsupported ZIP encoding",
                )
                if info.is_dir():
                    continue
                relative = "/".join(path.parts[1:])
                _require(relative not in entries, "duplicate ZIP path")
                entries[relative] = (
                    archive.read(info),
                    stat.S_IMODE(info.external_attr >> 16),
                )
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise ReleaseError("invalid release ZIP") from exc
    return entries


def prepare(source_root, repository, tag, config):
    root = Path(source_root).resolve()
    recipe = validate_recipe(root, repository, tag, config)
    pending = {}
    for payload in recipe["payload_sources"]:
        data = _download_payload(payload["url"], payload["bytes"])
        _require(
            len(data) == payload["bytes"] and _digest(data) == payload["sha256"],
            "payload size or SHA256 mismatch",
        )
        entries = _archive(data, recipe["extension_id"])
        _require("extension.yaml" in entries, "source payload lacks extension manifest")
        manifest = _yaml(entries["extension.yaml"][0], "payload manifest")
        _require(
            manifest.get("extension_id") == recipe["extension_id"]
            and manifest.get("version") == _release_url(payload["url"], repository),
            "payload manifest identity mismatch",
        )
        if payload["target"]:
            _require(".fs-package.yaml" in entries, "payload lacks target metadata")
            metadata = _yaml(entries[".fs-package.yaml"][0], "payload target metadata")
            _require(
                metadata.get("runtime_target") == payload["target"],
                "payload runtime target mismatch",
            )
        for name in payload["restore_paths"]:
            _require(name in entries, f"missing declared payload: {name}")
            content, mode = entries[name]
            _require(
                mode in {0o644, 0o755}
                and (not name.startswith("bin/") or mode == 0o755),
                "payload mode is invalid",
            )
            if name in pending:
                _require(
                    pending[name] == (content, mode), "conflicting restored payloads"
                )
            pending[name] = (content, mode)
            path = _path(root, name)
            if path.exists():
                _require(
                    path.is_file()
                    and path.read_bytes() == content
                    and stat.S_IMODE(path.stat().st_mode) == mode,
                    "refusing to overwrite existing source payload",
                )
    for name, (content, mode) in pending.items():
        path = _path(root, name)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(content)
            path.chmod(mode)
    return recipe


def _git(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=False
    )
    _require(result.returncode == 0, "git source identity check failed")
    return result.stdout


def _clean_source(root):
    sha = _git(root, "rev-parse", "HEAD").decode().strip()
    _require(re.fullmatch("[0-9a-f]{40}", sha), "invalid source commit SHA")
    _git(root, "diff", "--quiet", "HEAD", "--")
    return sha


def _checker(catalog_root):
    root = Path(catalog_root).resolve()
    path = _path(root, "scripts/build_index.py", exists=True)
    spec = importlib.util.spec_from_file_location("trusted_release_catalog", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, root


def _inspect(path, repository, tag, extension_id, target, catalog_root):
    checker, root = _checker(catalog_root)
    entry = checker.Entry(
        extension_id, "https://github.com/" + repository, *repository.split("/")
    )
    try:
        checker.inspect_archive(
            path.read_bytes(),
            entry=entry,
            version=tag[1:],
            categories=set(_json(root / "categories.json")),
            publishers=_json(root / "verified_publishers.json"),
            target=target,
        )
    except Exception as exc:
        raise ReleaseError(f"catalog archive validation failed: {exc}") from exc


def _tracked_package(root, recipe, target, destination):
    paths = set(_git(root, "ls-files", "-z").decode().rstrip("\0").split("\0"))
    paths.update(
        name
        for payload in recipe["payload_sources"]
        for name in payload["restore_paths"]
    )
    top = recipe["extension_id"].replace(".", "_").replace("-", "_")
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name in sorted(paths):
            relative = _relative(name)
            if (
                any(part in EXCLUDED for part in relative.parts)
                or name in {".fs-package.yaml", ".fs-extension-install.yaml"}
                or name.endswith((".pyc", ".pyo"))
            ):
                continue
            if relative.parts[0] == "bin":
                raise ReleaseError(
                    "native payload requires a source packager with provenance/security checks"
                )
            path = _path(root, name, exists=True)
            _require(path.is_file(), "tracked package input must be a regular file")
            info = zipfile.ZipInfo(f"{top}/{name}", (2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (
                stat.S_IFREG | (0o755 if path.stat().st_mode & 0o111 else 0o644)
            ) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes(), compresslevel=9)
        if target:
            info = zipfile.ZipInfo(f"{top}/.fs-package.yaml", (2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(
                info,
                json.dumps({"runtime_target": target}, sort_keys=True) + "\n",
                compresslevel=9,
            )


def _asset(path, *, kind, target=""):
    data = path.read_bytes()
    _require(
        0 < len(data) <= MAX_ZIP_BYTES, "asset exceeds byte size limit or is empty"
    )
    return {
        "filename": path.name,
        "target": target,
        "bytes": len(data),
        "sha256": _digest(data),
        "kind": kind,
    }


def build(source_root, repository, tag, config, out_dir, catalog_root):
    root = Path(source_root).resolve()
    recipe = validate_recipe(root, repository, tag, config)
    source_sha = _clean_source(root)
    for payload in recipe["payload_sources"]:
        for name in payload["restore_paths"]:
            _require(
                _path(root, name, exists=True).is_file(),
                "missing prepared runtime payload",
            )
    out = Path(out_dir).resolve()
    _require(
        out != root and not out.is_symlink(), "output must differ from source root"
    )
    out.mkdir(parents=True, exist_ok=True)
    _require(not any(out.iterdir()), "output directory must be empty")
    assets = []
    with tempfile.TemporaryDirectory(prefix="flow-steward-release-") as temporary:
        staging = Path(temporary)
        for target in recipe["runtime_targets"]:
            filename = (
                recipe["extension_id"]
                + "-"
                + tag[1:]
                + ("-" + target if target else "")
                + ".zip"
            )
            # Source packagers may emit private inventories/sidecars. Only the expected ZIP enters artifacts.
            with tempfile.TemporaryDirectory(
                prefix="packager-", dir=staging
            ) as package_output:
                expected = Path(package_output) / filename
                if recipe.get("package_script"):
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(_path(root, recipe["package_script"], exists=True)),
                            "--runtime-target",
                            target,
                            "--out-dir",
                            package_output,
                        ],
                        cwd=root,
                        check=False,
                    )
                    _require(
                        result.returncode == 0,
                        "source packager failed; provenance/security failures cannot be bypassed",
                    )
                    _require(
                        expected.is_file() and not expected.is_symlink(),
                        "source packager did not produce the expected release asset",
                    )
                else:
                    _tracked_package(root, recipe, target, expected)
                _inspect(
                    expected,
                    repository,
                    tag,
                    recipe["extension_id"],
                    target,
                    catalog_root,
                )
                assets.append(_asset(expected, kind="extension", target=target))
                shutil.copyfile(expected, staging / filename)
        tracked = set(_git(root, "ls-files", "-z").decode().split("\0"))
        for name in recipe["additional_assets"]:
            _require(name in tracked, "additional assets must be tracked source files")
            path = _path(root, name, exists=True)
            _require(
                path.name not in {PLAN, *[row["filename"] for row in assets]},
                "additional asset filename collision",
            )
            destination = staging / path.name
            shutil.copyfile(path, destination)
            assets.append(_asset(destination, kind="additional"))
        _require(_clean_source(root) == source_sha, "source changed during packaging")
        plan = {
            "schema_version": 1,
            "repository": repository,
            "tag": tag,
            "source_sha": source_sha,
            "extension_id": recipe["extension_id"],
            "runtime_targets": recipe["runtime_targets"],
            "assets": assets,
        }
        if "notes_file" in recipe:
            plan["notes_file"] = Path(recipe["notes_file"]).name
        (staging / PLAN).write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
        verify_plan(staging, repository, tag, source_sha, catalog_root)
        for path in staging.iterdir():
            shutil.copyfile(path, out / path.name)
    return plan


def verify_plan(artifact_dir, repository, tag, source_sha, catalog_root):
    _identity(repository, tag)
    _require(
        isinstance(source_sha, str) and re.fullmatch("[0-9a-f]{40}", source_sha),
        "invalid expected source SHA",
    )
    root = Path(artifact_dir).resolve()
    plan = _json(_path(root, PLAN, exists=True))
    _keys(
        plan,
        {
            "schema_version",
            "repository",
            "tag",
            "source_sha",
            "extension_id",
            "runtime_targets",
            "assets",
            "notes_file",
        },
        {
            "schema_version",
            "repository",
            "tag",
            "source_sha",
            "extension_id",
            "runtime_targets",
            "assets",
        },
        "release plan",
    )
    _require(
        type(plan["schema_version"]) is int and plan["schema_version"] == 1,
        "unsupported plan schema",
    )
    _require(
        (plan["repository"], plan["tag"], plan["source_sha"])
        == (repository, tag, source_sha),
        "release plan identity mismatch",
    )
    _require(
        isinstance(plan["extension_id"], str)
        and re.fullmatch(
            r"flowsteward\.[a-z0-9]+(?:[.-][a-z0-9]+)*", plan["extension_id"]
        ),
        "invalid plan extension_id",
    )
    _targets(plan["runtime_targets"])
    _require(
        isinstance(plan["assets"], list) and 0 < len(plan["assets"]) <= 30,
        "invalid plan assets",
    )
    seen = {PLAN}
    targets = []
    for asset in plan["assets"]:
        _keys(
            asset,
            {"filename", "target", "bytes", "sha256", "kind"},
            {"filename", "target", "bytes", "sha256", "kind"},
            "release asset",
        )
        relative = _relative(asset["filename"])
        _require(
            len(relative.parts) == 1 and asset["filename"] not in seen,
            "duplicate or nested release asset filename",
        )
        seen.add(asset["filename"])
        _require(
            asset["kind"] in {"extension", "additional"}
            and isinstance(asset["target"], str),
            "invalid asset kind/target",
        )
        _require(
            type(asset["bytes"]) is int
            and 0 < asset["bytes"] <= MAX_ZIP_BYTES
            and isinstance(asset["sha256"], str)
            and re.fullmatch("[0-9a-f]{64}", asset["sha256"]),
            "invalid asset size/hash",
        )
        path = _path(root, asset["filename"], exists=True)
        _require(
            path.is_file()
            and path.stat().st_size == asset["bytes"]
            and _digest(path.read_bytes()) == asset["sha256"],
            "release asset size/SHA256 mismatch",
        )
        if asset["kind"] == "extension":
            target = asset["target"]
            _require(
                target in plan["runtime_targets"] and target not in targets,
                "duplicate or mismatched release target",
            )
            expected = (
                plan["extension_id"]
                + "-"
                + tag[1:]
                + ("-" + target if target else "")
                + ".zip"
            )
            _require(path.name == expected, "extension release filename mismatch")
            _inspect(path, repository, tag, plan["extension_id"], target, catalog_root)
            targets.append(target)
        else:
            _require(
                asset["target"] == "" and not path.name.endswith(".zip"),
                "additional assets cannot impersonate extension ZIPs",
            )
    if "notes_file" in plan:
        _require(
            isinstance(plan["notes_file"], str)
            and any(
                row["kind"] == "additional" and row["filename"] == plan["notes_file"]
                for row in plan["assets"]
            ),
            "notes_file must reference a hash-bound additional asset",
        )
    _require(
        set(targets) == set(plan["runtime_targets"]),
        "release plan is missing declared runtime targets",
    )
    _require(
        {p.name for p in root.iterdir()} == seen
        and all(p.is_file() and not p.is_symlink() for p in root.iterdir()),
        "artifact directory contains unlisted or unsafe entries",
    )
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ["prepare", "build"]:
        command = commands.add_parser(name)
        command.add_argument("--source-root", required=True, type=Path)
        command.add_argument("--repository", required=True)
        command.add_argument("--tag", required=True)
        command.add_argument("--config", required=True)
        if name == "build":
            command.add_argument("--out-dir", required=True, type=Path)
            command.add_argument("--catalog-root", required=True, type=Path)
    verify = commands.add_parser("verify-plan")
    verify.add_argument("--artifact-dir", required=True, type=Path)
    verify.add_argument("--repository", required=True)
    verify.add_argument("--tag", required=True)
    verify.add_argument("--source-sha", required=True)
    verify.add_argument("--catalog-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args.source_root, args.repository, args.tag, args.config)
        elif args.command == "build":
            result = build(
                args.source_root,
                args.repository,
                args.tag,
                args.config,
                args.out_dir,
                args.catalog_root,
            )
        else:
            result = verify_plan(
                args.artifact_dir,
                args.repository,
                args.tag,
                args.source_sha,
                args.catalog_root,
            )
    except (
        ReleaseError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        zipfile.BadZipFile,
    ) as exc:
        parser.exit(2, f"Release validation failed: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
