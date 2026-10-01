#!/usr/bin/env python3
"""Package this repository as a Flow Steward extension archive.

    python3 .github/scripts/package_extension.py   ->  dist/<extension_id>-<version>.zip

The archive is what ``flow-steward extensions bundle`` produces: every tracked
file under one top folder named after the id (``.`` and ``-`` become ``_``),
without the repository's own tooling (.github/) and without development caches.
"""

from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
# The product bundler leaves these out (core/application/tooling/extensions/bundle_extension.py).
EXCLUDED_DIRECTORIES = {
    ".fs-python", ".hypothesis", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__", "dev-wheels",
}
EXCLUDED_FILES = {".fs-extension-install.yaml", ".fs-package.yaml"}
REPOSITORY_TOOLING = {".github", "dist"}
MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_UNPACKED_BYTES = 150 * 1024 * 1024


def manifest_field(name: str) -> str:
    text = (ROOT / "extension.yaml").read_text(encoding="utf-8")
    match = re.search(rf"^{name}:\s*['\"]?([^'\"\s#]+)", text, re.M)
    if not match:
        sys.exit(f"extension.yaml has no {name}")
    return match.group(1)


def shipped_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    files = []
    for name in sorted(p for p in out.split("\0") if p):
        parts = PurePosixPath(name).parts
        if parts[0] in REPOSITORY_TOOLING or name in REPOSITORY_TOOLING:
            continue
        if any(part in EXCLUDED_DIRECTORIES for part in parts) or parts[-1] in EXCLUDED_FILES:
            continue
        if parts[0] == "bin":
            sys.exit("bin/ needs one archive per runtime target; see the catalog README")
        files.append(name)
    return files


def main() -> int:
    extension_id, version = manifest_field("extension_id"), manifest_field("version")
    folder = extension_id.replace(".", "_").replace("-", "_")
    out = ROOT / "dist" / f"{extension_id}-{version}.zip"
    out.parent.mkdir(exist_ok=True)
    unpacked = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in shipped_files():
            archive.write(ROOT / name, arcname=f"{folder}/{name}")
            unpacked += (ROOT / name).stat().st_size
    size = out.stat().st_size
    if size > MAX_ZIP_BYTES or unpacked > MAX_UNPACKED_BYTES:
        sys.exit(f"{out.name}: {size} zipped / {unpacked} unpacked bytes exceed Flow Steward's install limits")
    print(f"{out.relative_to(ROOT)}  {size / 2**20:.1f} MB zipped, {unpacked / 2**20:.1f} MB unpacked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
