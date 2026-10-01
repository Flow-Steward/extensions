"""Tests for the extension catalog builder. Run with `python -m pytest scripts`."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml

import build_index as builder

CATEGORIES = ["data", "messaging", "other"]
REPO = "https://github.com/acme/mailbox-extension"
SLUG = "acme/mailbox-extension"


def _manifest(**overrides) -> dict:
    manifest = {
        "manifest_version": 2,
        "extension_id": "acme.mailbox",
        "version": "1.0.0",
        "kind": "tool_provider",
        "display_name": "Acme Mailbox",
        "description": "Read and search Acme mailboxes from workflow steps without OAuth.",
        "listing": {
            "category": "messaging",
            "tags": ["email", "imap"],
            "summary": "Search Acme mailboxes from workflows.",
        },
        "features": ["tool", "action"],
        "required_scopes": ["extension:invoke", "artifact:write"],
    }
    manifest.update(overrides)
    return manifest


def _zip(manifest: dict | None = None, *, top: str = "acme_mailbox", extra: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if manifest is not None:
            archive.writestr(f"{top}/extension.yaml", yaml.safe_dump(manifest, sort_keys=False))
        archive.writestr(f"{top}/main.py", "print('ok')\n")
        for name, content in (extra or {}).items():
            archive.writestr(f"{top}/{name}", content)
    return buffer.getvalue()


class FakeGitHub:
    """Repositories, releases and assets held in memory."""

    def __init__(self) -> None:
        self.releases_by_repo: dict[str, list[dict]] = {}
        self.assets: dict[str, bytes] = {}
        self.owner_types: dict[str, str] = {}
        self.public_members: set[tuple[str, str]] = set()

    def release(self, slug: str, version: str, data: bytes, *, extension_id: str = "acme.mailbox", **flags) -> str:
        name = f"{extension_id}-{version}.zip"
        url = f"https://github.com/{slug}/releases/download/v{version}/{name}"
        self.assets[url] = data
        releases = self.releases_by_repo.setdefault(slug, [])
        same_tag = next((r for r in releases if r["tag_name"] == f"v{version}"), None)
        if same_tag is not None:
            # A tag is unique on GitHub: a family release is one release with
            # every variant's assets.
            same_tag["assets"].append({"name": name, "browser_download_url": url})
            return url
        releases.insert(
            0, {"tag_name": f"v{version}", "assets": [{"name": name, "browser_download_url": url}], **flags}
        )
        return url

    def repository(self, slug: str) -> dict:
        owner = slug.split("/")[0]
        return {"owner": {"login": owner, "type": self.owner_types.get(owner, "User")}}

    def releases(self, slug: str) -> list[dict]:
        return list(self.releases_by_repo.get(slug, []))

    def is_public_member(self, org: str, login: str) -> bool:
        return (org, login) in self.public_members

    def download(self, url: str, *, max_bytes: int) -> bytes:
        return self.assets[url]


def _run(repo: Path, *command: str) -> str:
    return subprocess.run(command, cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "categories.json").write_text(json.dumps({key: key.title() for key in CATEGORIES}))
    (tmp_path / "verified_publishers.json").write_text(json.dumps({"flowsteward": "Flow-Steward"}))
    (tmp_path / "extensions").mkdir()
    _run(tmp_path, "git", "init", "-q", "-b", "main")
    _run(tmp_path, "git", "config", "user.email", "t@example.test")
    _run(tmp_path, "git", "config", "user.name", "t")
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    _commit(tmp_path, "setup")
    return tmp_path


def _entry(repo: Path, extension_id: str = "acme.mailbox", repository: str = REPO) -> None:
    (repo / "extensions" / f"{extension_id}.yaml").write_text(f"repository: {repository}\n")


def _commit(repo: Path, message: str) -> None:
    _run(repo, "git", "add", "-A")
    _run(repo, "git", "commit", "-q", "--allow-empty", "-m", message)


def _inspect(data: bytes, version: str = "1.0.0") -> dict:
    entry = builder.parse_entry("acme.mailbox", f"repository: {REPO}\n")
    return builder.inspect_archive(
        data, entry=entry, version=version, categories=set(CATEGORIES), publishers={"flowsteward": "Flow-Steward"}
    )


# --- the entry file -------------------------------------------------------------------


def test_an_entry_is_one_repository_link():
    entry = builder.parse_entry("acme.mailbox", f"repository: {REPO}.git\n")
    assert (entry.owner, entry.repo, entry.repository) == ("acme", "mailbox-extension", REPO)


@pytest.mark.parametrize(
    ("name", "text", "message"),
    [
        ("AcmeMailbox", f"repository: {REPO}\n", "lowercase dotted extension_id"),
        ("acme.mailbox", "repository: https://gitlab.com/acme/x\n", "https://github.com/<owner>/<repo>"),
        ("acme.mailbox", f"repository: {REPO}\nname: Mailbox\n", "exactly one key"),
    ],
)
def test_an_entry_that_is_not_a_repository_link_says_why(name, text, message):
    with pytest.raises(builder.CatalogError, match=message):
        builder.parse_entry(name, text)


def test_one_repository_can_publish_a_family_of_extensions(repo):
    """Variants built from one codebase share a repository, each with its own id."""
    github = FakeGitHub()
    for name in ("postgres", "mysql"):
        extension_id = f"acme.db-{name}"
        github.release(
            SLUG, "1.0.0", _zip(_manifest(extension_id=extension_id), top=f"acme_db_{name}"),
            extension_id=extension_id,
        )
        _entry(repo, extension_id)

    report = builder.publish(github=github)

    assert sorted(report.recorded) == ["releases/acme.db-mysql/1.0.0.json", "releases/acme.db-postgres/1.0.0.json"]
    assert {item["extension_id"] for item in builder.build_index()["items"]} == {"acme.db-mysql", "acme.db-postgres"}


# --- one release archive -----------------------------------------------------------------


def test_every_field_is_derived_from_the_manifest_in_the_release():
    assert _inspect(_zip(_manifest())) == {
        "extension_id": "acme.mailbox",
        "version": "1.0.0",
        "name": "Acme Mailbox",
        "summary": "Search Acme mailboxes from workflows.",
        "description": "Read and search Acme mailboxes from workflow steps without OAuth.",
        "categories": ["messaging"],
        "capabilities": ["tool", "action"],
        "permissions_summary": ["artifact:write", "extension:invoke"],
        "setup_summary": "",
        "tags": ["email", "imap"],
        "publication_status": "published",
        "verification_status": "unverified",
    }


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"not a zip", "not a ZIP archive"),
        (_zip(None), "add extension.yaml"),
        (_zip(_manifest(), top="mailbox"), "inside the top folder 'acme_mailbox/'"),
        (_zip(_manifest(extension_id="acme.other")), "declares extension_id 'acme.other'"),
        (_zip(_manifest(version="1.0.1")), "the release tag is v1.0.0"),
        (_zip(_manifest(display_name="acme.mailbox")), "readable title"),
        (_zip(_manifest(description="Too short.")), "at least 40"),
        (_zip(_manifest(listing={"category": "shops"})), "one of: data, messaging, other"),
        (_zip(_manifest(), extra={"config.yaml": "api_key: sk-live-123\n"}), "must not carry secrets"),
        (_zip(_manifest(), extra={".env": "TOKEN=1\n"}), "key and environment files"),
        (_zip(_manifest(), extra={"k.txt": "-----BEGIN RSA PRIVATE KEY-----\n"}), "private key"),
        (_zip(_manifest(), extra={"bin/linux-amd64/tool": "x"}), "one archive per runtime target"),
        (
            _zip(
                _manifest(),
                extra={"extension-descriptor.yaml": "extension_id: acme.mailbox\nrelease_version: 0.9.0\n"},
            ),
            "release_version 0.9.0 must match version 1.0.0",
        ),
    ],
)
def test_a_release_that_cannot_be_installed_says_why(data, message):
    with pytest.raises(builder.CatalogError, match=message):
        _inspect(data)


def test_every_problem_in_a_release_is_reported_at_once():
    with pytest.raises(builder.CatalogError) as caught:
        _inspect(_zip(_manifest(display_name="acme.mailbox", description="short")))
    assert "readable title" in str(caught.value) and "at least 40" in str(caught.value)


def test_names_of_secret_fields_are_not_leaks():
    schema = "properties:\n  password:\n    type: string\nauth:\n  secret_names:\n    access_token: access_token\n"
    assert _inspect(_zip(_manifest(), extra={"schemas/secrets.schema.yaml": schema}))


def test_caches_in_an_archive_are_ignored():
    assert _inspect(_zip(_manifest(), extra={"__pycache__/main.pyc": "x"}))


# --- publishing ---------------------------------------------------------------------------


def test_a_new_entry_records_its_latest_release_with_the_served_digest(repo):
    github = FakeGitHub()
    github.release(SLUG, "0.9.0", _zip(_manifest(version="0.9.0")))
    url = github.release(SLUG, "1.0.0", _zip(_manifest()))
    _entry(repo)

    report = builder.publish(github=github)

    assert report.recorded == ["releases/acme.mailbox/1.0.0.json"]
    [item] = builder.build_index()["items"]
    assert item["release_zip_url"] == url
    assert item["release_zip_sha256"] == hashlib.sha256(github.assets[url]).hexdigest()
    assert item["release_zip_bytes"] == len(github.assets[url])
    assert item["repository_url"] == f"{REPO}/tree/v1.0.0"
    assert "compatible_flow_steward" not in item


def test_later_releases_are_published_automatically(repo):
    github = FakeGitHub()
    github.release(SLUG, "1.0.0", _zip(_manifest()))
    _entry(repo)
    builder.publish(github=github)
    github.release(SLUG, "1.1.0", _zip(_manifest(version="1.1.0")))
    github.release(SLUG, "1.2.0-beta.1", _zip(_manifest(version="1.2.0-beta.1")), prerelease=True)

    report = builder.publish(github=github)

    assert report.recorded == ["releases/acme.mailbox/1.1.0.json"]
    assert builder.build_index()["items"][0]["version"] == "1.1.0"


def test_an_extension_records_when_it_entered_the_catalog_and_when_this_release_did(repo, monkeypatch):
    github = FakeGitHub()
    github.release(SLUG, "1.0.0", _zip(_manifest()))
    _entry(repo)
    monkeypatch.setattr(builder, "_now", lambda: "2026-09-01T08:00:00Z")
    builder.publish(github=github)
    github.release(SLUG, "1.1.0", _zip(_manifest(version="1.1.0")))
    monkeypatch.setattr(builder, "_now", lambda: "2026-09-20T09:30:00Z")
    builder.publish(github=github)

    [item] = builder.build_index()["items"]

    assert item["version"] == "1.1.0"
    assert item["added_at"] == "2026-09-01T08:00:00Z"
    assert item["updated_at"] == "2026-09-20T09:30:00Z"


def test_the_index_names_every_category(repo):
    assert builder.build_index()["category_labels"] == {"data": "Data", "messaging": "Messaging", "other": "Other"}


def test_a_category_list_without_names_is_refused(repo):
    (repo / "categories.json").write_text(json.dumps(CATEGORIES))

    with pytest.raises(builder.CatalogError, match="map each category id"):
        builder.build_index()


def test_a_broken_release_is_reported_and_the_previous_one_stays_listed(repo):
    github = FakeGitHub()
    github.release(SLUG, "1.0.0", _zip(_manifest()))
    _entry(repo)
    builder.publish(github=github)
    github.release(SLUG, "1.1.0", _zip(_manifest(version="1.0.0")))

    report = builder.publish(github=github)

    assert report.recorded == []
    assert any("the release tag is v1.1.0" in problem for problem in report.problems)
    assert builder.build_index()["items"][0]["version"] == "1.0.0"


def test_one_authors_broken_release_does_not_block_another(repo):
    github = FakeGitHub()
    github.release(SLUG, "1.0.0", b"broken")
    crm = _zip(_manifest(extension_id="beta.crm", version="2.0.0"), top="beta_crm")
    github.release("beta/crm", "2.0.0", crm, extension_id="beta.crm")
    _entry(repo)
    _entry(repo, "beta.crm", "https://github.com/beta/crm")

    report = builder.publish(github=github)

    assert report.recorded == ["releases/beta.crm/2.0.0.json"]
    assert [item["extension_id"] for item in builder.build_index()["items"]] == ["beta.crm"]


def test_a_swapped_asset_is_withdrawn_and_the_previous_release_listed(repo):
    github = FakeGitHub()
    github.release(SLUG, "1.0.0", _zip(_manifest()))
    _entry(repo)
    builder.publish(github=github)
    url = github.release(SLUG, "1.1.0", _zip(_manifest(version="1.1.0")))
    builder.publish(github=github)
    github.assets[url] = _zip(_manifest(version="1.1.0"), extra={"payload.py": "import os\n"})

    report = builder.publish(github=github)

    assert report.withdrawn == ["releases/acme.mailbox/1.1.0.json"]
    [item] = builder.build_index()["items"]
    assert item["version"] == "1.0.0"


def test_publishing_again_changes_nothing(repo):
    github = FakeGitHub()
    github.release(SLUG, "1.0.0", _zip(_manifest()))
    _entry(repo)
    builder.publish(github=github)
    first = builder.render(builder.build_index())

    report = builder.publish(github=github)

    assert (report.recorded, report.withdrawn, report.problems) == ([], [], [])
    assert builder.render(builder.build_index()) == first


def test_a_removed_entry_stays_listed_as_deprecated(repo):
    github = FakeGitHub()
    github.release(SLUG, "1.0.0", _zip(_manifest()))
    _entry(repo)
    builder.publish(github=github)
    (repo / "extensions" / "acme.mailbox.yaml").unlink()

    assert builder.build_index()["items"][0]["publication_status"] == "deprecated"


def test_a_reserved_namespace_is_verified_from_its_owner(repo):
    github = FakeGitHub()
    manifest = _manifest(extension_id="flowsteward.mailbox")
    github.release(
        "Flow-Steward/mailbox", "1.0.0", _zip(manifest, top="flowsteward_mailbox"), extension_id="flowsteward.mailbox"
    )
    _entry(repo, "flowsteward.mailbox", "https://github.com/Flow-Steward/mailbox")

    builder.publish(github=github)

    assert builder.build_index()["items"][0]["verification_status"] == "verified"


# --- pull requests ------------------------------------------------------------------------


def _pull_request(repo: Path, extension_id: str = "acme.mailbox", repository: str = REPO) -> None:
    _run(repo, "git", "branch", "-q", "base")
    _entry(repo, extension_id, repository)
    _commit(repo, "submit")


def test_the_owner_can_submit_a_repository_with_an_installable_release(repo):
    github = FakeGitHub()
    github.release(SLUG, "1.0.0", _zip(_manifest()))
    _pull_request(repo)

    assert builder.check_pull_request(base="base", submitter="acme", github=github) == []


def test_a_public_member_of_the_owning_organization_can_submit(repo):
    github = FakeGitHub()
    github.release(SLUG, "1.0.0", _zip(_manifest()))
    github.owner_types["acme"] = "Organization"
    github.public_members.add(("acme", "dev1"))
    _pull_request(repo)

    assert builder.check_pull_request(base="base", submitter="dev1", github=github) == []


def test_someone_else_cannot_submit_another_persons_repository(repo):
    github = FakeGitHub()
    github.release(SLUG, "1.0.0", _zip(_manifest()))
    _pull_request(repo)

    [problem] = builder.check_pull_request(base="base", submitter="mallory", github=github)
    assert "does not own" in problem


def test_a_repository_without_a_release_cannot_be_submitted(repo):
    _pull_request(repo)

    [problem] = builder.check_pull_request(base="base", submitter="acme", github=FakeGitHub())
    assert "has no release yet" in problem


def test_a_submission_whose_release_is_broken_says_why(repo):
    github = FakeGitHub()
    github.release(SLUG, "1.0.0", _zip(_manifest(description="short")))
    _pull_request(repo)

    [problem] = builder.check_pull_request(base="base", submitter="acme", github=github)
    assert "at least 40" in problem


def test_a_reserved_namespace_cannot_be_claimed(repo):
    _pull_request(repo, "flowsteward.mailbox", "https://github.com/mallory/mailbox")

    [problem] = builder.check_pull_request(base="base", submitter="mallory", github=FakeGitHub())
    assert "reserved for github.com/Flow-Steward" in problem


def test_moving_a_listed_extension_to_another_repository_is_refused(repo):
    _entry(repo)
    _commit(repo, "listed")
    _pull_request(repo, repository="https://github.com/mallory/mailbox")

    [problem] = builder.check_pull_request(base="base", submitter="mallory", github=FakeGitHub())
    assert "needs a maintainer" in problem


def test_a_pull_request_may_not_write_generated_files(repo):
    _run(repo, "git", "branch", "-q", "base")
    (repo / "index.json").write_text("{}")
    _commit(repo, "hand edit")

    [problem] = builder.check_pull_request(base="base", submitter="acme", github=FakeGitHub())
    assert "written by the publish job" in problem


# --- native extensions: one archive per runtime target --------------------------------------

_MACHINE = {"linux-amd64": 62, "linux-arm64": 183}


def _elf(target: str, payload: bytes = b"toolbox") -> bytes:
    header = b"\x7fELF\x02\x01" + b"\0" * 12 + _MACHINE[target].to_bytes(2, "little")
    return header + payload


def _native_zip(target: str, *, binary: bytes | None = None, metadata: dict | None = None,
                mode: int = 0o755, extra: dict[str, bytes] | None = None) -> bytes:
    """What `flow-steward extensions bundle --runtime-target <target>` produces."""
    binary = _elf(target) if binary is None else binary
    files = {
        "extension.yaml": yaml.safe_dump(_manifest(), sort_keys=False).encode(),
        "main.py": b"print('ok')\n",
        f"bin/{target}/toolbox": binary,
        ".fs-package.yaml": yaml.safe_dump(
            metadata
            if metadata is not None
            else {
                "native_executable": {
                    "path": f"bin/{target}/toolbox",
                    "sha256": hashlib.sha256(binary).hexdigest(),
                },
                "runtime_target": target,
            }
        ).encode(),
        **(extra or {}),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, blob in files.items():
            info = zipfile.ZipInfo(f"acme_mailbox/{name}")
            info.external_attr = ((mode if name.startswith("bin/") else 0o644) | 0o100000) << 16
            archive.writestr(info, blob)
    return buffer.getvalue()


def _inspect_native(data: bytes, target: str = "linux-amd64") -> dict:
    entry = builder.parse_entry("acme.mailbox", f"repository: {REPO}\n")
    return builder.inspect_archive(
        data, entry=entry, version="1.0.0", categories=set(CATEGORIES), publishers={}, target=target
    )


def _native_release(github: FakeGitHub, targets=("linux-amd64", "linux-arm64")) -> dict[str, str]:
    urls = {}
    release = {"tag_name": "v1.0.0", "assets": []}
    for target in targets:
        name = f"acme.mailbox-1.0.0-{target}.zip"
        url = f"https://github.com/{SLUG}/releases/download/v1.0.0/{name}"
        github.assets[url] = _native_zip(target)
        release["assets"].append({"name": name, "browser_download_url": url})
        urls[target] = url
    github.releases_by_repo.setdefault(SLUG, []).insert(0, release)
    return urls


def test_a_bundled_per_target_archive_passes():
    assert _inspect_native(_native_zip("linux-arm64"), "linux-arm64")["version"] == "1.0.0"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (_native_zip("linux-amd64", metadata={}), "runtime_target"),
        (_native_zip("linux-amd64", binary=_elf("linux-arm64")), "is not a linux-amd64 ELF64"),
        (
            _native_zip("linux-amd64", metadata={
                "runtime_target": "linux-amd64",
                "native_executable": {"path": "bin/linux-amd64/toolbox", "sha256": "0" * 64},
            }),
            "SHA-256 differs",
        ),
        (_native_zip("linux-amd64", mode=0o644), "must be executable"),
        (_native_zip("linux-amd64", extra={"bin/linux-arm64/toolbox": _elf("linux-arm64")}), "may only carry bin/linux-amd64/"),
        (_native_zip("linux-amd64", extra={"tools/helper": _elf("linux-amd64", b"x")}), "exactly one native executable"),
    ],
)
def test_a_per_target_archive_the_installer_would_refuse_says_why(data, message):
    with pytest.raises(builder.CatalogError, match=message):
        _inspect_native(data)


def test_a_per_target_release_lists_every_target_and_defaults_to_amd64(repo):
    github = FakeGitHub()
    urls = _native_release(github)
    _entry(repo)

    assert builder.publish(github=github).recorded == ["releases/acme.mailbox/1.0.0.json"]
    [item] = builder.build_index()["items"]

    assert item["release_zip_url"] == urls["linux-amd64"]
    assert set(item["release_targets"]) == {"linux-amd64", "linux-arm64"}
    for target, url in urls.items():
        artifact = item["release_targets"][target]
        assert artifact["release_zip_url"] == url
        assert artifact["release_zip_sha256"] == hashlib.sha256(github.assets[url]).hexdigest()


def test_a_per_target_release_without_amd64_is_refused(repo):
    github = FakeGitHub()
    _native_release(github, targets=("linux-arm64",))
    _entry(repo)

    report = builder.publish(github=github)

    assert report.recorded == []
    assert any("must include acme.mailbox-1.0.0-linux-amd64.zip" in p for p in report.problems)


def test_a_swapped_target_archive_withdraws_the_release(repo):
    github = FakeGitHub()
    urls = _native_release(github)
    _entry(repo)
    builder.publish(github=github)
    github.assets[urls["linux-arm64"]] = _native_zip("linux-arm64", binary=_elf("linux-arm64", b"evil"))

    report = builder.publish(github=github)

    assert report.withdrawn == ["releases/acme.mailbox/1.0.0.json"]
    assert builder.build_index()["items"] == []


# --- per-architecture archives without a native executable (Python wheels) -----------------

_ARM_WHEEL = "numpy-2.4.2-cp312-cp312-manylinux_2_28_aarch64.whl"
_X86_WHEEL = "numpy-2.4.2-cp312-cp312-manylinux_2_28_x86_64.whl"


def _wheel_zip(target: str, wheels: list[str], *, binary: bytes | None = None) -> bytes:
    files = {
        "extension.yaml": yaml.safe_dump(_manifest(), sort_keys=False).encode(),
        ".fs-package.yaml": yaml.safe_dump({"runtime_target": target}).encode(),
        **{f"wheels/{name}": b"wheel" for name in wheels},
    }
    if binary is not None:
        files[f"bin/{target}/helper"] = binary
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, blob in files.items():
            archive.writestr(f"acme_mailbox/{name}", blob)
    return buffer.getvalue()


def test_a_wheel_only_target_archive_passes():
    data = _wheel_zip("linux-arm64", [_ARM_WHEEL, "packaging-26.3-py3-none-any.whl"])
    assert _inspect_native(data, "linux-arm64")["version"] == "1.0.0"


def test_a_target_archive_with_another_platforms_wheels_is_refused():
    with pytest.raises(builder.CatalogError, match="wheels for another platform"):
        _inspect_native(_wheel_zip("linux-arm64", [_ARM_WHEEL, _X86_WHEEL]), "linux-arm64")


def test_a_target_archive_declaring_no_executable_may_not_carry_one():
    data = _wheel_zip("linux-arm64", [_ARM_WHEEL], binary=_elf("linux-arm64"))
    with pytest.raises(builder.CatalogError, match="declares no native_executable"):
        _inspect_native(data, "linux-arm64")
