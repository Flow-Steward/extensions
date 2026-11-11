"""Offline release trust-boundary tests; run with Python 3.12 and pytest."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import stat
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).parent
REPOSITORY = "Flow-Steward/ext-fixture"
TAG = "v0.1.1"
EXTENSION_ID = "flowsteward.fixture"


def test_cli_provides_release_subcommands():
    result = subprocess.run(
        [sys.executable, str(HERE / "release_extension.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert all(
        command in result.stdout for command in ["prepare", "build", "verify-plan"]
    )


@pytest.fixture
def helper():
    path = HERE / "release_extension.py"
    assert path.is_file(), "shared release helper has not been implemented"
    spec = importlib.util.spec_from_file_location("release_extension_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    return path


def commit(root):
    for args in [
        ("init", "-q"),
        ("add", "."),
        (
            "-c",
            "user.name=Release Test",
            "-c",
            "user.email=release@example.invalid",
            "commit",
            "-qm",
            "fixture",
            "--no-gpg-sign",
        ),
    ]:
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    manifest = {
        "manifest_version": 2,
        "extension_id": EXTENSION_ID,
        "version": "0.1.1",
        "kind": "tool_provider",
        "display_name": "Release fixture",
        "description": "A representative release fixture with enough customer description text.",
        "listing": {
            "category": "data",
            "summary": "A fixture for offline release validation.",
        },
        "features": ["tool"],
        "required_scopes": ["extension:invoke"],
        "runtime": {"contract_version": "extension_host_v2"},
    }
    write(root, "extension.yaml", yaml.safe_dump(manifest))
    write(
        root,
        "extension-descriptor.yaml",
        json.dumps({"extension_id": EXTENSION_ID, "release_version": "0.1.1"}),
    )
    write(root, "main.py", "VALUE = 7\n")
    write(root, "README.md", "Fixture release\n")
    write(
        root,
        "icon.png",
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", 128, 128),
    )
    write(root, ".gitignore", "bin/\nwheels/\npackages.txt\ndist/\n")
    return root


def recipe(root, *, targets=None, payloads=None, script=None, **extra):
    data = dict(
        schema_version=1,
        extension_id=EXTENSION_ID,
        runtime_targets=targets
        if targets is not None
        else ["linux-amd64", "linux-arm64"],
        payload_sources=payloads or [],
        test_requirements=[],
        test_paths=[],
        additional_assets=[],
        **extra,
    )
    if script is not None:
        data["package_script"] = script
    write(root, ".github/release-config.json", json.dumps(data))
    return data


def archive(
    files=None,
    *,
    unsafe=None,
    symlink=False,
    target="linux-amd64",
    extension_id=EXTENSION_ID,
):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        for name, content in {
            "extension.yaml": yaml.safe_dump(
                {"extension_id": extension_id, "version": "0.1.0"}
            ),
            ".fs-package.yaml": json.dumps({"runtime_target": target}),
            **(files or {}),
        }.items():
            info = zipfile.ZipInfo("flowsteward_fixture/" + name)
            info.create_system = 3
            info.external_attr = (
                stat.S_IFREG | (0o755 if name.startswith("bin/") else 0o644)
            ) << 16
            z.writestr(info, content)
        if unsafe:
            info = zipfile.ZipInfo(unsafe)
            info.create_system = 3
            info.external_attr = (
                (stat.S_IFLNK if symlink else stat.S_IFREG) | 0o755
            ) << 16
            z.writestr(info, "outside")
    return stream.getvalue()


def payload(data, *, paths=None, **changes):
    return dict(
        target="linux-amd64",
        url="https://github.com/Flow-Steward/ext-fixture/releases/download/v0.1.0/fixture.zip",
        bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        restore_paths=paths or ["bin/linux-amd64/toolbox"],
        **changes,
    )


def prepare(helper, root):
    return helper.prepare(root, REPOSITORY, TAG, ".github/release-config.json")


def build(helper, root, out):
    return helper.build(
        root, REPOSITORY, TAG, ".github/release-config.json", out, HERE.parent
    )


def test_prepare_restores_verified_binary_and_mode(helper, source, monkeypatch):
    data = archive({"bin/linux-amd64/toolbox": b"original native bytes"})
    recipe(source, payloads=[payload(data)])
    monkeypatch.setattr(helper, "_download_payload", lambda url, limit: data)
    prepare(helper, source)
    path = source / "bin/linux-amd64/toolbox"
    assert path.read_bytes() == b"original native bytes"
    assert stat.S_IMODE(path.stat().st_mode) == 0o755
    prepare(helper, source)  # an identical existing file is verified, never overwritten
    assert path.read_bytes() == b"original native bytes"


@pytest.mark.parametrize(
    "mutation",
    ["hash", "size", "traversal", "symlink", "wrong-id", "wrong-target", "missing"],
)
def test_prepare_rejects_bad_payload_without_writes(
    helper, source, monkeypatch, mutation
):
    data = archive(
        {"bin/linux-amd64/toolbox": b"native"},
        unsafe="flowsteward_fixture/../../escape"
        if mutation == "traversal"
        else "flowsteward_fixture/link"
        if mutation == "symlink"
        else None,
        symlink=mutation == "symlink",
        extension_id="flowsteward.other" if mutation == "wrong-id" else EXTENSION_ID,
        target="linux-arm64" if mutation == "wrong-target" else "linux-amd64",
    )
    entry = payload(data)
    if mutation == "hash":
        entry["sha256"] = "0" * 64
    if mutation == "size":
        entry["bytes"] += 1
    if mutation == "missing":
        entry["restore_paths"] = ["wheels/missing.whl"]
    recipe(source, payloads=[entry])
    monkeypatch.setattr(helper, "_download_payload", lambda url, limit: data)
    with pytest.raises(helper.ReleaseError):
        prepare(helper, source)
    assert not (source / "bin").exists()
    assert not (source.parent / "escape").exists()


def test_prepare_does_not_overwrite_source(helper, source, monkeypatch):
    data = archive({"bin/linux-amd64/toolbox": b"prior"})
    recipe(source, payloads=[payload(data)])
    write(source, "bin/linux-amd64/toolbox", b"current")
    monkeypatch.setattr(helper, "_download_payload", lambda url, limit: data)
    with pytest.raises(helper.ReleaseError):
        prepare(helper, source)
    assert (source / "bin/linux-amd64/toolbox").read_bytes() == b"current"


@pytest.mark.parametrize(
    "change",
    [
        {"unknown": True},
        {"schema_version": True},
        {"runtime_targets": ["linux-amd64"]},
        {"test_paths": "tests"},
        {"package_script": "main.py"},
    ],
)
def test_recipe_rejects_unknown_fields_and_wrong_types(helper, source, change):
    config = recipe(source)
    config.update(change)
    write(source, ".github/release-config.json", json.dumps(config))
    with pytest.raises(helper.ReleaseError):
        prepare(helper, source)


@pytest.mark.parametrize(
    "mutation",
    ["other-repo", "http", "credentials", "restore-source", "tag", "descriptor"],
)
def test_prepare_rejects_identity_url_or_restore_scope(
    helper, source, monkeypatch, mutation
):
    data = archive({"bin/linux-amd64/toolbox": b"native"})
    entry = payload(data)
    if mutation == "other-repo":
        entry["url"] = entry["url"].replace("ext-fixture/", "ext-other/")
    if mutation == "http":
        entry["url"] = entry["url"].replace("https:", "http:")
    if mutation == "credentials":
        entry["url"] = entry["url"].replace("github.com", "user:password@github.com")
    if mutation == "restore-source":
        entry["restore_paths"] = ["main.py"]
    recipe(source, payloads=[entry])
    if mutation == "descriptor":
        write(
            source,
            "extension-descriptor.yaml",
            json.dumps(
                {"extension_id": "flowsteward.other", "release_version": "0.1.1"}
            ),
        )
    monkeypatch.setattr(helper, "_download_payload", lambda url, limit: data)
    with pytest.raises(helper.ReleaseError):
        helper.prepare(
            source,
            REPOSITORY,
            "v0.1.2" if mutation == "tag" else TAG,
            ".github/release-config.json",
        )


def test_tracked_packaging_is_deterministic_and_excludes_ci_and_output(
    helper, source, tmp_path
):
    recipe(source)
    sha = commit(source)
    first = source / "dist"
    second = tmp_path / "second"
    build(helper, source, first)
    build(helper, source, second)
    for name in [
        f"{EXTENSION_ID}-0.1.1-linux-amd64.zip",
        f"{EXTENSION_ID}-0.1.1-linux-arm64.zip",
    ]:
        assert (first / name).read_bytes() == (second / name).read_bytes()
        with zipfile.ZipFile(first / name) as z:
            names = z.namelist()
            assert "flowsteward_fixture/main.py" in names
            assert not any(
                "/.github/" in n or "/.git/" in n or "/dist/" in n for n in names
            )
    plan = json.loads((first / "release-plan.json").read_text())
    assert plan["source_sha"] == sha
    helper.verify_plan(first, REPOSITORY, TAG, sha, HERE.parent)


def test_existing_packager_failure_and_changed_provenance_are_fatal(
    helper, source, tmp_path, monkeypatch
):
    script = "from pathlib import Path\nimport sys\nroot=Path(__file__).resolve().parents[1]\nif (root/'bin/linux-amd64/toolbox').read_bytes()!=b'current required binary':\n sys.exit('provenance mismatch')\n"
    write(source, "scripts/package_extension.py", script)
    data = archive({"bin/linux-amd64/toolbox": b"stale prior binary"})
    recipe(source, payloads=[payload(data)], script="scripts/package_extension.py")
    commit(source)
    monkeypatch.setattr(helper, "_download_payload", lambda url, limit: data)
    prepare(helper, source)
    with pytest.raises(helper.ReleaseError, match="packager"):
        build(helper, source, tmp_path / "out")
    assert not list((tmp_path / "out").glob("*.zip"))


def test_build_requires_declared_payload_and_clean_tracked_source(
    helper, source, tmp_path
):
    recipe(source, payloads=[payload(archive())])
    commit(source)
    with pytest.raises(helper.ReleaseError):
        build(helper, source, tmp_path / "missing")
    recipe(source)
    commit(source)
    write(source, "main.py", "UNCOMMITTED = True\n")
    with pytest.raises(helper.ReleaseError):
        build(helper, source, tmp_path / "dirty")


@pytest.mark.parametrize(
    "mutation",
    [
        "hash",
        "repository",
        "tag",
        "sha",
        "filename",
        "target",
        "missing-target",
        "extra-file",
        "symlink",
        "unknown",
    ],
)
def test_verify_plan_rejects_tampering_without_running_source(
    helper, source, tmp_path, mutation
):
    recipe(source, targets=[""])
    sha = commit(source)
    out = tmp_path / "out"
    build(helper, source, out)
    plan_path = out / "release-plan.json"
    plan = json.loads(plan_path.read_text())
    if mutation == "hash":
        plan["assets"][0]["sha256"] = "0" * 64
    if mutation == "repository":
        plan["repository"] = "Flow-Steward/ext-other"
    if mutation == "tag":
        plan["tag"] = "v0.1.2"
    if mutation == "sha":
        plan["source_sha"] = "a" * 40
    if mutation == "filename":
        plan["assets"][0]["filename"] = "../escape.zip"
    if mutation == "target":
        plan["assets"][0]["target"] = "linux-arm64"
    if mutation == "missing-target":
        plan["assets"] = []
    if mutation == "extra-file":
        write(out, "unlisted.zip", b"extra")
    if mutation == "symlink":
        item = out / plan["assets"][0]["filename"]
        saved = item.read_bytes()
        item.unlink()
        elsewhere = write(tmp_path, "elsewhere", saved)
        item.symlink_to(elsewhere)
    if mutation == "unknown":
        plan["publish_command"] = "touch forbidden"
    plan_path.write_text(json.dumps(plan))
    with pytest.raises(helper.ReleaseError):
        helper.verify_plan(out, REPOSITORY, TAG, sha, HERE.parent)


def test_additional_assets_are_copied_hashed_and_checked(helper, source, tmp_path):
    recipe(source, targets=[""])
    config = json.loads((source / ".github/release-config.json").read_text())
    config["additional_assets"] = ["README.md"]
    write(source, ".github/release-config.json", json.dumps(config))
    sha = commit(source)
    out = tmp_path / "out"
    build(helper, source, out)
    assert (out / "README.md").read_bytes() == b"Fixture release\n"
    helper.verify_plan(out, REPOSITORY, TAG, sha, HERE.parent)
    (out / "README.md").write_text("tampered")
    with pytest.raises(helper.ReleaseError):
        helper.verify_plan(out, REPOSITORY, TAG, sha, HERE.parent)


def test_source_packager_success_is_checked_and_used(helper, source, tmp_path):
    script = """import argparse,json,zipfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--runtime-target');p.add_argument('--out-dir');a=p.parse_args()
r=Path(__file__).resolve().parents[1];o=Path(a.out_dir);o.mkdir(parents=True,exist_ok=True)
(o/'SHA256SUMS').write_text('packager-owned output inventory')
with zipfile.ZipFile(o/f'flowsteward.fixture-0.1.1-{a.runtime_target}.zip','w') as z:
 for n in ['extension.yaml','extension-descriptor.yaml','icon.png','main.py','README.md']:
  z.write(r/n,'flowsteward_fixture/'+n)
 z.writestr('flowsteward_fixture/from-source-packager.txt','packaged by source')
 z.writestr('flowsteward_fixture/.fs-package.yaml',json.dumps({'runtime_target':a.runtime_target}))
"""
    write(source, "scripts/package_extension.py", script)
    recipe(source, script="scripts/package_extension.py")
    sha = commit(source)
    out = tmp_path / "out"
    build(helper, source, out)
    with zipfile.ZipFile(out / f"{EXTENSION_ID}-0.1.1-linux-amd64.zip") as z:
        assert (
            z.read("flowsteward_fixture/from-source-packager.txt")
            == b"packaged by source"
        )
    assert not (out / "SHA256SUMS").exists()
    helper.verify_plan(out, REPOSITORY, TAG, sha, HERE.parent)


def test_notes_file_is_an_explicit_hash_bound_additional_asset(
    helper, source, tmp_path
):
    recipe(source, targets=[""], notes_file="RELEASE_NOTES.md")
    write(source, "RELEASE_NOTES.md", "Customer release notes\n")
    config = json.loads((source / ".github/release-config.json").read_text())
    config["additional_assets"] = ["RELEASE_NOTES.md"]
    write(source, ".github/release-config.json", json.dumps(config))
    sha = commit(source)
    out = tmp_path / "out"
    build(helper, source, out)
    plan = json.loads((out / "release-plan.json").read_text())
    assert plan["notes_file"] == "RELEASE_NOTES.md"
    helper.verify_plan(out, REPOSITORY, TAG, sha, HERE.parent)
    plan["notes_file"] = "unlisted.md"
    (out / "release-plan.json").write_text(json.dumps(plan))
    with pytest.raises(helper.ReleaseError):
        helper.verify_plan(out, REPOSITORY, TAG, sha, HERE.parent)


def test_notes_file_cannot_reference_undeclared_source(helper, source):
    write(source, "RELEASE_NOTES.md", "notes")
    recipe(source, notes_file="RELEASE_NOTES.md")
    with pytest.raises(helper.ReleaseError):
        prepare(helper, source)
