#!/usr/bin/env python3
"""Turn an extension folder into its own repository, ready for this catalog.

    python3 scripts/new_extension_repo.py <extension folder> <new repository dir> \\
        --repository https://github.com/<owner>/<repo>

Copies the extension's tracked files (without dev-wheels), adds the CI and
release workflows and packaging scripts from templates/single-extension/,
adds the default logo `icon.png` when the extension has none, points the
manifest's support and website links at the new repository, and makes the
first commit. Push it, tag ``v<version>``, then run the printed catalog
registration command for a Flow Steward maintained repository. External authors
submit ``extensions/<extension_id>.yaml`` by pull request.
"""

from __future__ import annotations

import argparse
import re
import shutil
import shlex
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "single-extension"
# The neutral "package" logo Flow Steward's own scaffold writes; replace it with yours.
DEFAULT_ICON = ROOT / "templates" / "default-icon.png"
_REPOSITORY = re.compile(r"^https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
_SKIPPED = {"dev-wheels", "__pycache__", ".pytest_cache", ".fs-python", "bin"}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _tracked(source: Path) -> list[str]:
    top = Path(_git(source, "rev-parse", "--show-toplevel").strip())
    prefix = source.resolve().relative_to(top).as_posix() + "/"
    return [
        path[len(prefix):]
        for path in _git(top, "ls-files", "-z", "--", prefix).split("\0")
        if path.startswith(prefix)
    ]


def _write_test_requirements(target: Path) -> None:
    """.github/requirements-test.txt: the manifest's python_requirements.

    Under .github/ with the rest of the repository tooling, so it is never part of
    the extension package (and package layout tests do not see it).
    """
    import yaml

    manifest = yaml.safe_load((target / "extension.yaml").read_text(encoding="utf-8")) or {}
    pins = [
        f"{row['name']}=={row['version']}"
        for row in manifest.get("python_requirements") or []
        if isinstance(row, dict) and row.get("name") and row.get("version")
    ]
    if pins:
        (target / ".github").mkdir(exist_ok=True)
        (target / ".github" / "requirements-test.txt").write_text(
            "# Installed by CI for the tests; the runtime installs python_requirements itself.\n"
            + "\n".join(pins) + "\n",
            encoding="utf-8",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--repository", required=True)
    args = parser.parse_args(argv)
    if not _REPOSITORY.match(args.repository):
        sys.exit("--repository must look like https://github.com/<owner>/<repo>")
    if not (args.source / "extension.yaml").is_file():
        sys.exit(f"{args.source} has no extension.yaml")
    if args.target.exists():
        sys.exit(f"{args.target} already exists")

    copied = skipped = 0
    for relative in _tracked(args.source):
        path = PurePosixPath(relative)
        # The extension SDK wheel stays for the tests: the host provides the SDK at
        # runtime, and it is not on PyPI yet. Other dev wheels come from PyPI.
        keep_sdk = path.parts[0] == "dev-wheels" and path.name.startswith("flowsteward_extension_sdk-")
        if set(path.parts) & _SKIPPED and not keep_sdk:
            skipped += 1
            continue
        destination = args.target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.source / relative, destination)
        copied += 1
    if (args.source / "bin").exists():
        print("note: bin/ was not copied — a native executable needs per-target archives; "
              "see Flow-Steward/ext-data-connector-mcp-toolbox for how to build them in CI")
    for template_file in TEMPLATE.rglob("*"):
        if template_file.is_file():
            destination = args.target / template_file.relative_to(TEMPLATE)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(template_file, destination)

    if not (args.target / "icon.png").is_file():
        shutil.copy2(DEFAULT_ICON, args.target / "icon.png")
        print("note: icon.png is the default package logo; replace it with your own "
              "(PNG, square, 32-512 px, at most 100 KB)")
    _write_test_requirements(args.target)
    manifest = args.target / "extension.yaml"
    text = manifest.read_text(encoding="utf-8")
    text = re.sub(r"(^\s*support_url:\s*).*$", rf"\g<1>{args.repository}/issues", text, flags=re.M)
    text = re.sub(r"(^\s*website_url:\s*).*$", rf"\g<1>{args.repository}", text, flags=re.M)
    manifest.write_text(text, encoding="utf-8")

    _git(args.target.parent, "init", "-q", "-b", "main", str(args.target))
    _git(args.target, "add", "-A")
    print(f"{args.target}: {copied} files copied, {skipped} left out (dev-wheels, caches, bin/)")
    if args.repository.startswith("https://github.com/Flow-Steward/ext-"):
        import yaml

        metadata = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        version = metadata.get("version") if isinstance(metadata, dict) else None
        if isinstance(version, str) and re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
            print("After publishing the stable tag, register and verify catalog delivery:")
            print(shlex.join([
                "gh", "workflow", "run", "register-extension.yml", "--repo", "Flow-Steward/extensions",
                "-f", "repository=" + args.repository.removeprefix("https://github.com/").removesuffix(".git"),
                "-f", f"tag=v{version}",
            ]))
        else:
            print("note: publish a stable version matching extension.yaml before catalog registration")
    return 0


if __name__ == "__main__":
    sys.exit(main())
