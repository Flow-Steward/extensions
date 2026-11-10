"""Discover dependency declarations without importing or executing inspected code."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename

REPOSITORY = re.compile(
    r"https://github\.com/([A-Za-z0-9-]+/[A-Za-z0-9._-]+)(?:\.git)?/?$"
)
IGNORED = {
    ".git",
    ".venv",
    ".fs-python",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
}
UNSUPPORTED = {
    "Dockerfile",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Pipfile.lock",
    "Gemfile.lock",
    "Cargo.lock",
    "composer.lock",
    "Cargo.toml",
    "Gemfile",
    "composer.json",
    "Pipfile",
}


@dataclass(frozen=True, order=True)
class Extension:
    extension_id: str
    version: str
    repository: str
    tag: str


@dataclass(frozen=True, order=True)
class Dependency:
    ecosystem: str
    name: str
    version: str
    source: str
    scope: str = "runtime"
    commit: str = ""


@dataclass
class Inventory:
    dependencies: list[Dependency] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)


def select_extensions(root: Path) -> list[Extension]:
    """Ownership comes from registrations, not an extension ID or vendor claim."""
    registrations = {}
    for path in sorted((root / "extensions").glob("*.yaml")):
        entry = yaml.safe_load(path.read_text())
        match = REPOSITORY.fullmatch(entry.get("repository", ""))
        if not match:
            raise ValueError(f"invalid source registration: {path.name}")
        slug = match[1].removesuffix(".git")
        if slug.split("/")[0].lower() == "flow-steward":
            registrations[path.stem] = slug
    selected = []
    for item in json.loads((root / "index.json").read_text())["items"]:
        key = item["extension_id"]
        if key not in registrations or item.get("publication_status") != "published":
            continue
        version = item["version"]
        if not re.fullmatch(r"[0-9][A-Za-z0-9.+-]*", version):
            raise ValueError(f"invalid published version: {key}")
        slug, tag = registrations[key], f"v{version}"
        if (
            item["repository_url"].lower()
            != f"https://github.com/{slug}/tree/{tag}".lower()
        ):
            raise ValueError(
                f"catalog source disagrees with registration/version: {key}"
            )
        selected.append(Extension(key, version, slug, tag))
    if not selected:
        raise ValueError("no published Flow-Steward extensions selected")
    return sorted(selected)


def relevant_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return not any(p in IGNORED for p in parts) and ".." not in parts


def source_file(path: str) -> bool:
    """Only small declarative files need fetching; wheel names come from the tree."""
    name = PurePosixPath(path).name
    return relevant_path(path) and (
        name
        in {
            "extension.yaml",
            "pyproject.toml",
            "uv.lock",
            "poetry.lock",
            "package-lock.json",
            "go.mod",
            "THIRD_PARTY.yml",
        }
        or name.endswith("-provenance.json")
        or requirements_file(path)
    )


def requirements_file(path: str) -> bool:
    file = PurePosixPath(path)
    return file.suffix in {".txt", ".in"} and (
        file.name.startswith(("requirements", "constraints"))
        or "requirements" in file.parts
    )


def _scope(path: str) -> str:
    return "development" if re.search(r"dev|test|\.github", path) else "runtime"


def discover(files: dict[str, str], paths: list[str]) -> Inventory:
    result = Inventory()
    custom_python_source = any(
        requirements_file(path)
        and re.search(
            r"(?m)^\s*(?:--(?:extra-index-url|index-url|find-links|no-index)|-[if](?:\s|https?:))",
            content,
        )
        for path, content in files.items()
    )

    def add(eco, name, version, source, scope="runtime", commit=""):
        if not isinstance(name, str) or not name or not isinstance(version, str):
            raise ValueError("invalid dependency name/version")
        if eco == "PyPI":
            name = canonicalize_name(name)
        result.dependencies.append(
            Dependency(eco, name, version, source, scope, commit)
        )

    def requirement(value, path, scope):
        value = re.sub(r"\s+--hash=\S+", "", value).strip()
        if not value or value.startswith("#"):
            return
        if value.startswith(("-r ", "--requirement ", "-c ", "--constraint ")):
            target = str(PurePosixPath(path).parent / value.split(maxsplit=1)[1])
            if target not in files:
                result.gaps.append(f"{path}: included file is unavailable: {target}")
            return  # Each present file is parsed once, including cycles.
        if value.endswith(".whl") and "://" not in value:
            name, version, _, _ = parse_wheel_filename(PurePosixPath(value).name)
            add("PyPI", name, str(version), path, scope)
            return
        if value.startswith("-"):
            result.gaps.append(
                f"{path}: unsupported requirements option (custom indexes are not resolved)"
            )
            return
        req = Requirement(re.split(r"\s+#", value, maxsplit=1)[0])
        if req.url:
            result.gaps.append(
                f"{path}: direct URL dependency {req.name} needs source/version mapping"
            )
            return
        specs = list(req.specifier)
        version = (
            specs[0].version
            if len(specs) == 1
            and specs[0].operator == "=="
            and "*" not in specs[0].version
            else ""
        )
        add("PyPI", req.name, version, path, scope)

    for path in sorted(set(paths) | set(files)):
        if not relevant_path(path):
            continue
        name = PurePosixPath(path).name
        scope = _scope(path)
        try:
            if name.endswith(".whl"):
                package, version, _, _ = parse_wheel_filename(name)
                add("PyPI", package, str(version), path, scope)
            elif (
                name in UNSUPPORTED
                or name.startswith("Dockerfile.")
                or name == "package.json"
            ):
                if (
                    name != "package.json"
                    or str(PurePosixPath(path).with_name("package-lock.json"))
                    not in files
                ):
                    result.gaps.append(
                        f"{path}: dependency format not covered; add a supported lockfile or adapter"
                    )
            elif path not in files:
                continue
            elif name == "extension.yaml":
                data = yaml.safe_load(files[path]) or {}
                requirements = data.get("python_requirements", [])
                if not isinstance(requirements, list):
                    raise ValueError("python_requirements must be a list")
                for req in requirements:
                    if isinstance(req, str):
                        requirement(req, path, "runtime")
                    else:
                        add("PyPI", req["name"], str(req.get("version", "")), path)
            elif requirements_file(path):
                for line in files[path].replace("\\\n", " ").splitlines():
                    try:
                        requirement(line, path, scope)
                    except (ValueError, TypeError) as exc:
                        result.gaps.append(
                            f"{path}: {type(exc).__name__}: invalid requirement"
                        )
            elif name == "pyproject.toml":
                data = tomllib.loads(files[path])
                project = data.get("project", {})
                for req in project.get("dependencies", []):
                    requirement(req, path, "runtime")
                for group in project.get("optional-dependencies", {}).values():
                    for req in group:
                        requirement(req, path, "optional")
                for req in data.get("build-system", {}).get("requires", []):
                    requirement(req, path, "build")
                if "dependencies" in project.get("dynamic", []):
                    result.gaps.append(
                        f"{path}: dynamic dependencies cannot be evaluated statically"
                    )
                if (
                    data.get("tool", {}).get("poetry", {}).get("dependencies")
                    and str(PurePosixPath(path).with_name("poetry.lock")) not in files
                ):
                    result.gaps.append(
                        f"{path}: Poetry dependencies require poetry.lock"
                    )
            elif name in {"uv.lock", "poetry.lock"}:
                for package in tomllib.loads(files[path]).get("package", []):
                    source = package.get("source", {})
                    if (
                        "editable" in source
                        or "virtual" in source
                        or source.get("type") == "directory"
                    ):
                        continue
                    registry = source.get(
                        "registry", source.get("url", "https://pypi.org/simple")
                    )
                    if (
                        registry.rstrip("/")
                        not in {
                            "https://pypi.org/simple",
                            "https://pypi.python.org/simple",
                        }
                        or source.get("git")
                        or source.get("type") in {"git", "url", "file"}
                    ):
                        result.gaps.append(
                            f"{path}: non-PyPI dependency {package['name']} needs mapping"
                        )
                        continue
                    groups = package.get("groups", [])
                    dev = package.get("category") == "dev" or (
                        groups and "main" not in groups
                    )
                    add(
                        "PyPI",
                        package["name"],
                        package["version"],
                        path,
                        "development" if dev else scope,
                    )
            elif name.endswith("-provenance.json") or name == "THIRD_PARTY.yml":
                data = (
                    json.loads(files[path])
                    if name.endswith(".json")
                    else yaml.safe_load(files[path])
                )
                url = data.get("source", data.get("source_url", ""))
                match = REPOSITORY.fullmatch(url) if isinstance(url, str) else None
                if not match:
                    result.gaps.append(
                        f"{path}: upstream source is not a supported GitHub repository"
                    )
                    continue
                version = str(
                    data.get("upstream_tag", data.get("tag", data.get("version", "")))
                )
                commit = data.get("upstream_commit", data.get("commit", ""))
                if commit and not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
                    raise ValueError("upstream commit must be a SHA")
                add(
                    "GitHub",
                    match[1].removesuffix(".git"),
                    version,
                    path,
                    "upstream",
                    commit,
                )
            elif name == "go.mod":
                for package, version in go_requirements(files[path], result.gaps, path):
                    add("Go", package, version, path)
            elif name == "package-lock.json":
                data = json.loads(files[path])
                if data.get("lockfileVersion") not in {2, 3}:
                    result.gaps.append(
                        f"{path}: only npm lockfile versions 2 and 3 are supported"
                    )
                    continue
                for location, package in data.get("packages", {}).items():
                    if not location or package.get("link"):
                        continue
                    package_name = (
                        package.get("name") or location.rsplit("node_modules/", 1)[-1]
                    )
                    version = package.get("version", "")
                    resolved = package.get("resolved", "")
                    if resolved and (
                        urlsplit(resolved).scheme != "https"
                        or urlsplit(resolved).netloc
                        not in {"registry.npmjs.org", "registry.yarnpkg.com"}
                    ):
                        result.gaps.append(
                            f"{path}: non-public-registry npm dependency {package_name} needs source mapping"
                        )
                        continue
                    if not re.fullmatch(
                        r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.+-]+)?", version
                    ):
                        result.gaps.append(
                            f"{path}: non-registry npm dependency {package_name}"
                        )
                        continue
                    add(
                        "npm",
                        package_name,
                        version,
                        path,
                        "development" if package.get("dev") else scope,
                    )
        except (ValueError, TypeError, KeyError, AttributeError, yaml.YAMLError) as exc:
            result.gaps.append(
                f"{path}: cannot parse dependency metadata ({type(exc).__name__})"
            )
    if custom_python_source:
        result.dependencies = [
            d
            for d in result.dependencies
            if d.ecosystem != "PyPI"
            or PurePosixPath(d.source).name in {"uv.lock", "poetry.lock"}
        ]
        result.gaps.append(
            "Python registry/find-links override detected: inferred PyPI identities skipped; only explicit public lockfile sources are checked"
        )
    result.dependencies = sorted(set(result.dependencies))
    pinned = {
        (d.ecosystem, d.name) for d in result.dependencies if d.version or d.commit
    }
    for dep in result.dependencies:
        if (
            not dep.version
            and not dep.commit
            and (dep.ecosystem, dep.name) not in pinned
        ):
            result.gaps.append(
                f"{dep.source}: {dep.name} has no exact version; vulnerability/update checks unavailable"
            )
    result.gaps = sorted(set(result.gaps))
    return result


def go_requirements(content: str, gaps: list[str], path: str) -> list[tuple[str, str]]:
    """Read require/replace blocks; go.sum alone is not an installed inventory."""
    requires, replacements = {}, []
    block = ""
    for raw in content.splitlines():
        line = raw.split("//", 1)[0].strip()
        if line == ")":
            block = ""
            continue
        if line in {"require (", "replace ("}:
            block = line.split()[0]
            continue
        fields = line.split()
        if not fields:
            continue
        kind = block or fields.pop(0)
        if kind == "require" and len(fields) == 2:
            requires[fields[0]] = fields[1]
        elif kind == "replace" and "=>" in fields:
            split = fields.index("=>")
            replacements.append((fields[:split], fields[split + 1 :]))
        elif kind in {"exclude", "retract"}:
            gaps.append(f"{path}: {kind} directives require Go module resolution")
    for old, new in replacements:
        if old[0] not in requires or (len(old) > 1 and requires[old[0]] != old[1]):
            continue
        requires.pop(old[0])
        if len(new) == 2:
            requires[new[0]] = new[1]
        else:
            gaps.append(
                f"{path}: local Go replacement {old[0]} cannot be version-checked"
            )
    return sorted(requires.items())
