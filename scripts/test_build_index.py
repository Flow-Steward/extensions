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
        self.releases_by_repo.setdefault(slug, []).insert(
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
    (tmp_path / "categories.json").write_text(json.dumps(CATEGORIES))
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


def test_one_repository_cannot_back_two_entries(repo):
    _entry(repo, "acme.mailbox")
    _entry(repo, "acme.inbox")

    with pytest.raises(builder.CatalogError, match="already listed"):
        builder.load_entries()


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
        (_zip(_manifest(), extra={"bin/linux-amd64/tool": "x"}), "native per-platform payloads"),
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
