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


def _run(repo: Path, *command: str) -> str:
    return subprocess.run(command, cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "categories.json").write_text(json.dumps(CATEGORIES))
    (tmp_path / "verified_publishers.json").write_text(json.dumps(["acme"]))
    _run(tmp_path, "git", "init", "-q", "-b", "main")
    _run(tmp_path, "git", "config", "user.email", "t@example.test")
    _run(tmp_path, "git", "config", "user.name", "t")
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    _commit(tmp_path, "setup")
    return tmp_path


def _write(repo: Path, manifest: dict, folder: str = "acme_mailbox", extra: dict | None = None) -> None:
    base = repo / "extensions" / folder
    base.mkdir(parents=True, exist_ok=True)
    (base / "extension.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    (base / "main.py").write_text("print('ok')\n")
    for relative, content in (extra or {}).items():
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def _commit(repo: Path, message: str) -> None:
    _run(repo, "git", "add", "-A")
    _run(repo, "git", "commit", "-q", "--allow-empty", "-m", message)


class FakeReleases:
    """Stands in for GitHub Releases: keeps what was uploaded, serves it back."""

    def __init__(self) -> None:
        self.assets: dict[str, bytes] = {}

    def __call__(self, tag: str, file_name: str, payload: bytes, commit: str) -> tuple[str, bytes]:
        self.assets.setdefault(tag, payload)
        return f"https://github.com/acme/extensions/releases/download/{tag}/{file_name}", self.assets[tag]


def _publish(repo: Path, releases: FakeReleases | None = None) -> list[str]:
    written = builder.publish(repository="acme/extensions", uploader=releases or FakeReleases())
    _commit(repo, "publish")
    return written


# --- one folder --------------------------------------------------------------------


def test_every_field_is_derived_from_the_manifest(repo):
    _write(repo, _manifest())
    _commit(repo, "add")

    [source] = builder.load_sources()

    assert source.item == {
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
        "verification_status": "verified",
    }


def test_the_summary_falls_back_to_the_first_sentence(repo):
    manifest = _manifest(description="Read Acme mail. Then a lot more detail about how it works.")
    del manifest["listing"]["summary"]
    _write(repo, manifest)
    _commit(repo, "add")

    assert builder.load_sources()[0].item["summary"] == "Read Acme mail."


def test_a_publisher_outside_the_verified_list_is_unverified(repo):
    _write(repo, _manifest(extension_id="other.mailbox"), folder="other_mailbox")
    _commit(repo, "add")

    assert builder.load_sources()[0].item["verification_status"] == "unverified"


def test_the_archive_holds_one_top_folder_and_only_tracked_files(repo):
    _write(repo, _manifest(), extra={"schemas/config.schema.yaml": "type: object\n"})
    _commit(repo, "add")
    base = repo / "extensions" / "acme_mailbox"
    (base / "__pycache__").mkdir()
    (base / "__pycache__" / "main.cpython-312.pyc").write_bytes(b"\0")
    (base / "notes.txt").write_text("untracked")

    [source] = builder.load_sources()
    with zipfile.ZipFile(io.BytesIO(builder.build_zip(source))) as archive:
        names = sorted(archive.namelist())

    assert names == [
        "acme_mailbox/extension.yaml",
        "acme_mailbox/main.py",
        "acme_mailbox/schemas/config.schema.yaml",
    ]


@pytest.mark.parametrize(
    ("manifest", "extra", "message"),
    [
        (_manifest(extension_id="AcmeMailbox"), {}, "lowercase dotted id"),
        (_manifest(extension_id="acme.inbox"), {}, "must be named 'acme_inbox'"),
        (_manifest(version="1.0"), {}, "semantic"),
        (_manifest(display_name="acme.mailbox"), {}, "readable title"),
        (_manifest(description="Too short."), {}, "at least 40"),
        (_manifest(listing={"summary": "x"}), {}, "set listing.category"),
        (_manifest(listing={"category": "shops"}), {}, "use one of: data, messaging, other"),
        (_manifest(), {"config.yaml": "api_key: sk-live-123\n"}, "must not carry secrets"),
        (_manifest(), {".env": "TOKEN=1\n"}, "key and environment files"),
        (_manifest(), {"certs/k.txt": "-----BEGIN RSA PRIVATE KEY-----\n"}, "private key"),
        (_manifest(), {"bin/linux-amd64/tool": "x"}, "native per-platform payloads"),
        (
            _manifest(version="1.1.0"),
            {"extension-descriptor.yaml": "extension_id: acme.mailbox\nrelease_version: 1.0.0\n"},
            "release_version 1.0.0 must match version 1.1.0",
        ),
    ],
)
def test_a_folder_that_cannot_be_published_says_why(repo, manifest, extra, message):
    _write(repo, manifest, extra=extra)
    _commit(repo, "add")

    with pytest.raises(builder.CatalogError, match=message):
        builder.load_sources()


def test_every_problem_in_a_folder_is_reported_at_once(repo):
    _write(repo, _manifest(version="1", description="short"))
    _commit(repo, "add")

    with pytest.raises(builder.CatalogError) as caught:
        builder.load_sources()
    assert "semantic" in str(caught.value) and "at least 40" in str(caught.value)


def test_a_schema_that_names_a_secret_field_is_not_a_leak(repo):
    schema = "type: object\nproperties:\n  password:\n    type: string\n"
    _write(repo, _manifest(), extra={"schemas/secrets.schema.yaml": schema})
    _commit(repo, "add")

    assert builder.load_sources()


def test_a_map_of_secret_names_is_not_a_leak(repo):
    contract = "auth:\n  secret_names:\n    access_token: access_token\n"
    _write(repo, _manifest(), extra={"contracts/connection_types.yaml": contract})
    _commit(repo, "add")

    assert builder.load_sources()


def test_two_folders_cannot_publish_the_same_extension(repo):
    _write(repo, _manifest())
    _write(repo, _manifest(), folder="acme_mailbox_copy")
    _commit(repo, "add")

    with pytest.raises(builder.CatalogError):
        builder.load_sources()


# --- releases and the index ----------------------------------------------------------


def test_publishing_records_the_served_bytes_and_the_index_lists_them(repo):
    _write(repo, _manifest())
    _commit(repo, "add")
    releases = FakeReleases()

    assert _publish(repo, releases) == ["releases/acme.mailbox/1.0.0.json"]
    index = builder.build_index()

    [item] = index["items"]
    served = releases.assets["acme.mailbox-v1.0.0"]
    assert item["release_zip_url"] == (
        "https://github.com/acme/extensions/releases/download/acme.mailbox-v1.0.0/acme.mailbox-1.0.0.zip"
    )
    assert item["release_zip_bytes"] == len(served)
    assert item["release_zip_sha256"] == hashlib.sha256(served).hexdigest()
    commit = _run(repo, "git", "log", "-1", "--format=%H", "--", "extensions/acme_mailbox")
    assert item["repository_url"] == f"https://github.com/acme/extensions/tree/{commit}/extensions/acme_mailbox"
    assert index["schema_version"] == "extension_catalog/v1"
    assert "compatible_flow_steward" not in item


def test_the_archive_declares_the_release_the_index_offers(repo):
    """Flow Steward refuses an archive whose own extension.yaml names another release."""
    _write(repo, _manifest())
    _commit(repo, "add")
    releases = FakeReleases()
    _publish(repo, releases)

    with zipfile.ZipFile(io.BytesIO(releases.assets["acme.mailbox-v1.0.0"])) as archive:
        declared = yaml.safe_load(archive.read("acme_mailbox/extension.yaml"))
    assert (declared["extension_id"], declared["version"]) == ("acme.mailbox", "1.0.0")


def test_a_rerun_after_an_uploaded_but_unrecorded_release_keeps_the_served_digest(repo):
    _write(repo, _manifest())
    _commit(repo, "add")
    releases = FakeReleases()
    releases.assets["acme.mailbox-v1.0.0"] = b"bytes uploaded by an earlier run"

    _publish(repo, releases)

    [item] = builder.build_index()["items"]
    assert item["release_zip_sha256"] == hashlib.sha256(b"bytes uploaded by an earlier run").hexdigest()


def test_publishing_again_releases_nothing_and_the_index_is_stable(repo):
    _write(repo, _manifest())
    _commit(repo, "add")
    _publish(repo)
    first = builder.render(builder.build_index())

    assert _publish(repo) == []
    assert builder.render(builder.build_index()) == first


def test_the_newest_release_is_listed(repo):
    _write(repo, _manifest())
    _commit(repo, "add")
    _publish(repo)
    _write(repo, _manifest(version="1.1.0"))
    _commit(repo, "bump")
    _publish(repo)

    [item] = builder.build_index()["items"]
    assert item["version"] == "1.1.0"
    assert sorted(p.name for p in (repo / "releases" / "acme.mailbox").iterdir()) == ["1.0.0.json", "1.1.0.json"]


def test_a_removed_folder_stays_listed_as_deprecated(repo):
    _write(repo, _manifest())
    _commit(repo, "add")
    _publish(repo)
    _run(repo, "git", "rm", "-rq", "extensions/acme_mailbox")
    _commit(repo, "remove")

    [item] = builder.build_index()["items"]
    assert item["publication_status"] == "deprecated"


# --- pull request checks --------------------------------------------------------------


def _released_base(repo: Path) -> None:
    _write(repo, _manifest())
    _commit(repo, "add")
    _publish(repo)
    _run(repo, "git", "branch", "-q", "base")


def test_changing_a_released_version_is_refused(repo):
    _released_base(repo)
    _write(repo, _manifest(), extra={"helper.py": "x = 1\n"})
    _commit(repo, "edit")

    assert builder.main(["--check", "--base", "base"]) == 1
    with pytest.raises(builder.CatalogError, match="raise version"):
        builder.check_versions(builder.load_sources(), builder.load_records())


def test_a_lower_version_is_refused(repo):
    _released_base(repo)
    _write(repo, _manifest(version="0.9.0"))
    _commit(repo, "downgrade")

    with pytest.raises(builder.CatalogError, match="higher than the released 1.0.0"):
        builder.check_versions(builder.load_sources(), builder.load_records())


def test_a_raised_version_passes(repo):
    _released_base(repo)
    _write(repo, _manifest(version="1.0.1"), extra={"helper.py": "x = 1\n"})
    _commit(repo, "bump")

    assert builder.main(["--check", "--base", "base"]) == 0


def test_a_pull_request_may_not_write_generated_files(repo):
    _released_base(repo)
    (repo / "index.json").write_text("{}")
    _commit(repo, "hand edit")

    assert builder.generated_file_changes("base") == ["index.json"]
    assert builder.main(["--check", "--base", "base"]) == 1
