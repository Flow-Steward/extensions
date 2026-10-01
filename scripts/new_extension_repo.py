#!/usr/bin/env python3
"""Turn an extension folder into its own repository, ready for this catalog.

    python3 scripts/new_extension_repo.py <extension folder> <new repository dir> \\
        --repository https://github.com/<owner>/<repo>

Copies the extension's tracked files (without dev-wheels), adds the CI and
release workflows and packaging scripts from templates/single-extension/,
points the manifest's support and website links at the new repository, and
makes the first commit. Push it, tag ``v<version>``, then add
``extensions/<extension_id>.yaml`` here.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "single-extension"
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


#: The extension SDK imports cryptography lazily but does not declare it yet; the
#: Flow Steward runtime provides this version.
_SDK_TEST_REQUIREMENTS = ("cryptography==50.0.0",)


def _write_test_requirements(target: Path) -> None:
    """.github/requirements-test.txt: the manifest's python_requirements, and what the SDK needs.

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
    if any((target / "dev-wheels").glob("flowsteward_extension_sdk-*.whl")):
        names = {pin.split("==", 1)[0].lower() for pin in pins}
        pins += [pin for pin in _SDK_TEST_REQUIREMENTS if pin.split("==", 1)[0] not in names]
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

    _write_test_requirements(args.target)
    manifest = args.target / "extension.yaml"
    text = manifest.read_text(encoding="utf-8")
    text = re.sub(r"(^\s*support_url:\s*).*$", rf"\g<1>{args.repository}/issues", text, flags=re.M)
    text = re.sub(r"(^\s*website_url:\s*).*$", rf"\g<1>{args.repository}", text, flags=re.M)
    manifest.write_text(text, encoding="utf-8")

    _git(args.target.parent, "init", "-q", "-b", "main", str(args.target))
    _git(args.target, "add", "-A")
    print(f"{args.target}: {copied} files copied, {skipped} left out (dev-wheels, caches, bin/)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
