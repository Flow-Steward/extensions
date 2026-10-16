"""The single-extension template's packaging and catalog check, and new_extension_repo.py.

An author's own CI runs these scripts, so a release without a valid logo fails
there, before it is published.
"""

from __future__ import annotations

import importlib.util
import shutil
import struct
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_SCRIPTS = ROOT / "templates" / "single-extension" / ".github" / "scripts"
DEFAULT_ICON = ROOT / "templates" / "default-icon.png"
MANIFEST = "extension_id: acme.mailbox\nversion: 1.2.0\ndisplay_name: Acme Mailbox\n"


def _png(width: int = 128, height: int = 128, *, padding: int = 0) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", len(ihdr))
        + chunk
        + struct.pack(">I", zlib.crc32(chunk))
        + b"\0" * padding
    )


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _extension_repo(tmp_path: Path, icon: bytes | None) -> Path:
    repo = tmp_path / "acme-mailbox"
    scripts = repo / ".github" / "scripts"
    scripts.mkdir(parents=True)
    for name in ("package_extension.py", "catalog_check.py"):
        shutil.copy2(TEMPLATE_SCRIPTS / name, scripts / name)
    (repo / "extension.yaml").write_text(MANIFEST)
    (repo / "main.py").write_text("print('ok')\n")
    if icon is not None:
        (repo / "icon.png").write_bytes(icon)
    _git(repo.parent, "init", "-q", "-b", "main", str(repo))
    _git(repo, "add", "-A")
    return repo


def _package(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, ".github/scripts/package_extension.py"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_packaging_ships_the_logo(tmp_path):
    repo = _extension_repo(tmp_path, _png())

    proc = _package(repo)

    assert proc.returncode == 0, proc.stderr
    with zipfile.ZipFile(repo / "dist" / "acme.mailbox-1.2.0.zip") as archive:
        assert archive.read("acme_mailbox/icon.png") == _png()


@pytest.mark.parametrize(
    ("icon", "message"),
    [
        (None, "acme.mailbox 1.2.0: add icon.png (the extension's logo) next to extension.yaml"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "acme.mailbox 1.2.0: icon.png is not a PNG"),
        (_png(128, 64), "acme.mailbox 1.2.0: icon.png must be square, 32-512 px (is 128x64)"),
        (_png(16, 16), "acme.mailbox 1.2.0: icon.png must be square, 32-512 px (is 16x16)"),
        (_png(1024, 1024), "acme.mailbox 1.2.0: icon.png must be square, 32-512 px (is 1024x1024)"),
        (_png(padding=100 * 1024), "acme.mailbox 1.2.0: icon.png is larger than 102400 bytes"),
    ],
    ids=["missing", "svg", "not-square", "too-small", "too-large", "over-100kb"],
)
def test_packaging_refuses_a_missing_or_invalid_logo(tmp_path, icon, message):
    repo = _extension_repo(tmp_path, icon)

    proc = _package(repo)

    assert proc.returncode != 0
    assert message in proc.stderr
    assert not list((repo / "dist").glob("*.zip"))


def _catalog_check(repo: Path):
    spec = importlib.util.spec_from_file_location(
        "template_catalog_check", repo / ".github" / "scripts" / "catalog_check.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _archive(path: Path, icon: bytes | None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("acme_mailbox/extension.yaml", MANIFEST)
        if icon is not None:
            archive.writestr("acme_mailbox/icon.png", icon)
    return path


@pytest.mark.parametrize(
    ("icon", "message"),
    [
        (None, "acme.mailbox 1.2.0: add icon.png"),
        (b"GIF89a", "acme.mailbox 1.2.0: icon.png is not a PNG"),
        (_png(600, 600), "acme.mailbox 1.2.0: icon.png must be square, 32-512 px (is 600x600)"),
    ],
    ids=["missing", "gif", "too-large"],
)
def test_catalog_check_refuses_the_logo_even_when_the_catalog_is_unreachable(
    tmp_path, monkeypatch, capsys, icon, message
):
    module = _catalog_check(_extension_repo(tmp_path, _png()))

    def unreachable(_path: str) -> bytes:
        raise OSError("offline")

    monkeypatch.setattr(module, "_fetch", unreachable)
    archive = _archive(tmp_path / "acme.mailbox-1.2.0.zip", icon)

    assert module.main([str(archive)]) == 1
    assert message in capsys.readouterr().err


def test_catalog_check_accepts_a_valid_logo_when_the_catalog_is_unreachable(
    tmp_path, monkeypatch, capsys
):
    module = _catalog_check(_extension_repo(tmp_path, _png()))
    monkeypatch.setattr(module, "_fetch", lambda _path: (_ for _ in ()).throw(OSError("offline")))
    archive = _archive(tmp_path / "acme.mailbox-1.2.0.zip", _png(64, 64))

    assert module.main([str(archive)]) == 0
    assert "logo OK" in capsys.readouterr().out


def _source_extension(tmp_path: Path, icon: bytes | None) -> Path:
    source_repo = tmp_path / "source"
    folder = source_repo / "acme_mailbox"
    folder.mkdir(parents=True)
    (folder / "extension.yaml").write_text(MANIFEST + "vendor:\n  support_url: x\n  website_url: x\n")
    (folder / "main.py").write_text("print('ok')\n")
    if icon is not None:
        (folder / "icon.png").write_bytes(icon)
    _git(tmp_path, "init", "-q", "-b", "main", str(source_repo))
    _git(source_repo, "add", "-A")
    return folder


def _new_repo(source: Path, target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "new_extension_repo.py"),
            str(source),
            str(target),
            "--repository",
            "https://github.com/acme/mailbox-extension",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_new_extension_repo_writes_the_default_logo_when_there_is_none(tmp_path):
    source = _source_extension(tmp_path, None)
    target = tmp_path / "new-repo"

    proc = _new_repo(source, target)

    assert proc.returncode == 0, proc.stderr
    assert (target / "icon.png").read_bytes() == DEFAULT_ICON.read_bytes()
    assert "replace it with your own" in proc.stdout


def test_new_extension_repo_keeps_the_authors_logo(tmp_path):
    source = _source_extension(tmp_path, _png(256, 256))
    target = tmp_path / "new-repo"

    proc = _new_repo(source, target)

    assert proc.returncode == 0, proc.stderr
    assert (target / "icon.png").read_bytes() == _png(256, 256)


def test_the_default_logo_passes_the_catalog_rules():
    import build_index as builder

    problems, size = builder.icon_problems(DEFAULT_ICON.read_bytes())

    assert problems == []
    assert size == "128x128"
