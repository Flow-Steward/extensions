"""Registration and public catalog delivery, with real files and offline GitHub."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest
import yaml

import build_index as builder
import register_extension as registration
from test_build_index import FakeGitHub, _manifest, _zip

REPOSITORY = "Flow-Steward/ext-finance-b1"
REPOSITORY_URL = f"https://github.com/{REPOSITORY}"
SOURCE_SHA = "a" * 40
PUBLISHED_SHA = "b" * 40
INDEX_URL = f"https://raw.githubusercontent.com/Flow-Steward/extensions/{PUBLISHED_SHA}/index.json"


class OfflineGitHub(FakeGitHub):
    def __init__(self):
        super().__init__()
        self.metadata = {"full_name": REPOSITORY, "private": False}
        self.manifest_body = _manifest(extension_id="flowsteward.b1", version="0.1.0")
        self.commit = SOURCE_SHA
        self.manifest_requests = []
        self.index_failures = 0
        self.index_reads = 0
        self.release(
            REPOSITORY, "0.1.0",
            _zip(self.manifest_body, top="flowsteward_b1"),
            extension_id="flowsteward.b1", draft=False, prerelease=False,
        )

    def repository(self, slug):
        return copy.deepcopy(self.metadata)

    def source_commit(self, repository, tag):
        return self.commit

    def manifest(self, repository, commit, path):
        self.manifest_requests.append((repository, commit, path))
        return yaml.safe_dump(self.manifest_body).encode()

    def download(self, url, *, max_bytes):
        if url.endswith("/index.json"):
            self.index_reads += 1
            if self.index_failures:
                self.index_failures -= 1
                raise OSError("temporarily unavailable")
        return super().download(url, max_bytes=max_bytes)


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    (tmp_path / "extensions").mkdir()
    (tmp_path / "categories.json").write_text(json.dumps({"messaging": "Messaging"}))
    (tmp_path / "verified_publishers.json").write_text(json.dumps({"flowsteward": "Flow-Steward"}))
    return tmp_path


@pytest.fixture
def github():
    return OfflineGitHub()


def register(github, **kwargs):
    return registration.register(REPOSITORY, "v0.1.0", github=github, **kwargs)


def public_index():
    return {
        "schema_version": "extension_catalog/v1",
        "items": [{
            "extension_id": "flowsteward.b1",
            "version": "0.1.0",
            "publication_status": "published",
            "repository_url": f"{REPOSITORY_URL}/tree/v0.1.0",
            "release_zip_url": f"{REPOSITORY_URL}/releases/download/v0.1.0/flowsteward.b1-0.1.0.zip",
            "release_zip_sha256": "c" * 64,
            "release_zip_bytes": 123,
        }],
    }


def test_filename_comes_from_manifest_id_not_repository_slug(catalog, github):
    receipt = register(github)
    assert receipt["extension_id"] == "flowsteward.b1"
    assert receipt["version"] == "0.1.0"
    assert receipt["source_sha"] == SOURCE_SHA
    assert receipt["registration_path"] == "extensions/flowsteward.b1.yaml"
    assert receipt["changed"] is True
    assert (catalog / receipt["registration_path"]).read_text() == f"repository: {REPOSITORY_URL}\n"
    assert not (catalog / "extensions/ext-finance-b1.yaml").exists()
    assert github.manifest_requests == [(REPOSITORY, SOURCE_SHA, "extension.yaml")]


def test_identical_registration_is_not_rewritten(catalog, github):
    receipt = register(github)
    path = catalog / receipt["registration_path"]
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    again = register(github)
    assert again["changed"] is False
    assert path.stat().st_mtime_ns == 1_000_000_000


def test_conflicting_repository_is_not_replaced(catalog, github):
    path = catalog / "extensions/flowsteward.b1.yaml"
    previous = "repository: https://github.com/Flow-Steward/ext-other\n"
    path.write_text(previous)
    with pytest.raises(builder.CatalogError, match="already registered"):
        register(github)
    assert path.read_text() == previous


@pytest.mark.parametrize("field,value", [
    ("extension_id", "../escape"),
    ("extension_id", "ext-finance-b1"),
    ("extension_id", "flowsteward.b1\n"),
    ("extension_id", None),
    ("version", "0.2.0"),
    ("version", 1),
])
def test_invalid_manifest_identity_creates_no_registration(catalog, github, field, value):
    github.manifest_body[field] = value
    with pytest.raises(builder.CatalogError):
        register(github)
    assert list((catalog / "extensions").iterdir()) == []


@pytest.mark.parametrize("repository,tag,path", [
    ("other-owner/ext-test", "v0.1.0", "extension.yaml"),
    ("Flow-Steward/ext-test;echo", "v0.1.0", "extension.yaml"),
    (REPOSITORY, "main", "extension.yaml"),
    (REPOSITORY, "v0.1.0-beta.1", "extension.yaml"),
    (REPOSITORY, "v0.1.0", "../extension.yaml"),
    (REPOSITORY, "v0.1.0", "/extension.yaml"),
    (REPOSITORY, "v0.1.0", "a//extension.yaml"),
])
def test_unsafe_inputs_are_refused_without_writes(catalog, github, repository, tag, path):
    with pytest.raises(builder.CatalogError):
        registration.register(repository, tag, manifest_path=path, github=github)
    assert list((catalog / "extensions").iterdir()) == []


@pytest.mark.parametrize("metadata", [
    {"full_name": REPOSITORY, "private": True},
    {"full_name": "Flow-Steward/ext-other", "private": False},
])
def test_source_repository_must_be_expected_and_public(catalog, github, metadata):
    github.metadata = metadata
    with pytest.raises(builder.CatalogError, match="public repository"):
        register(github)
    assert list((catalog / "extensions").iterdir()) == []


@pytest.mark.parametrize("flag", ["draft", "prerelease"])
def test_nonpublic_or_prerelease_release_is_refused(catalog, github, flag):
    github.releases_by_repo[REPOSITORY][0][flag] = True
    with pytest.raises(builder.CatalogError, match="release"):
        register(github)
    assert list((catalog / "extensions").iterdir()) == []


def test_missing_release_is_refused(catalog, github):
    github.releases_by_repo[REPOSITORY] = []
    with pytest.raises(builder.CatalogError, match="release"):
        register(github)
    assert list((catalog / "extensions").iterdir()) == []


def test_bad_archive_is_refused_before_registration(catalog, github):
    url = next(iter(github.assets))
    github.assets[url] = _zip(_manifest(extension_id="flowsteward.other", version="0.1.0"), top="flowsteward_b1")
    with pytest.raises(builder.CatalogError, match="extension_id"):
        register(github)
    assert list((catalog / "extensions").iterdir()) == []


def test_changed_existing_release_bytes_are_not_accepted(catalog, github):
    entry = builder.parse_entry("flowsteward.b1", f"repository: {REPOSITORY_URL}\n")
    record = builder.fetch_release(entry, "0.1.0", github.releases(REPOSITORY)[0],
        github=github, categories={"messaging"}, publishers={"flowsteward": "Flow-Steward"})
    record["item"]["release_zip_sha256"] = "0" * 64
    builder.write_record(record)
    with pytest.raises(builder.CatalogError, match="existing release"):
        register(github)
    assert list((catalog / "extensions").iterdir()) == []


def test_registration_target_must_not_be_a_symlink(catalog, github):
    outside = catalog / "outside.yaml"
    outside.write_text("keep")
    (catalog / "extensions/flowsteward.b1.yaml").symlink_to(outside)
    with pytest.raises(builder.CatalogError):
        register(github)
    assert outside.read_text() == "keep"


def test_manifest_variant_path_is_read_at_resolved_commit(catalog, github):
    register(github, manifest_path="variants/b1/extension.yaml")
    assert github.manifest_requests == [(REPOSITORY, SOURCE_SHA, "variants/b1/extension.yaml")]


def test_public_catalog_must_contain_active_expected_identity(catalog, github):
    receipt = register(github)
    assert registration.verify_index(public_index(), receipt)["extension_id"] == "flowsteward.b1"


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "stale", "repository", "withdrawn", "schema"])
def test_incomplete_or_wrong_public_catalog_is_refused(catalog, github, mutation):
    receipt = register(github)
    index = public_index()
    if mutation == "missing":
        index["items"] = []
    elif mutation == "duplicate":
        index["items"].append(copy.deepcopy(index["items"][0]))
    elif mutation == "stale":
        index["items"][0]["version"] = "0.0.9"
    elif mutation == "repository":
        index["items"][0]["repository_url"] = "https://github.com/Flow-Steward/ext-other/tree/v0.1.0"
    elif mutation == "withdrawn":
        index["items"][0]["publication_status"] = "deprecated"
    else:
        index["schema_version"] = "other/v1"
    with pytest.raises(builder.CatalogError):
        registration.verify_index(index, receipt)


def test_newer_published_version_is_accepted(catalog, github):
    receipt = register(github)
    index = public_index()
    index["items"][0].update(
        version="0.2.0",
        repository_url=f"{REPOSITORY_URL}/tree/v0.2.0",
        release_zip_url=f"{REPOSITORY_URL}/releases/download/v0.2.0/flowsteward.b1-0.2.0.zip",
    )
    assert registration.verify_index(index, receipt)["version"] == "0.2.0"


def test_public_item_must_match_validated_archive_identity(catalog, github):
    receipt = register(github)
    index = public_index()
    expected = copy.deepcopy(index["items"][0])
    index["items"][0]["release_zip_sha256"] = "d" * 64
    with pytest.raises(builder.CatalogError, match="validated"):
        registration.verify_index(index, receipt, expected_item=expected)


def test_public_readback_retries_network_failures_then_verifies_commit(catalog, github, monkeypatch):
    receipt = register(github)
    index = public_index()
    github.assets[INDEX_URL] = json.dumps(index).encode()
    github.index_failures = 2
    monkeypatch.setattr(registration.time, "sleep", lambda _: None)
    result = registration.verify_published(receipt, PUBLISHED_SHA, index, github=github, attempts=3)
    assert result["extension_id"] == "flowsteward.b1"
    assert github.index_reads == 3


def test_public_readback_failure_is_bounded(catalog, github, monkeypatch):
    receipt = register(github)
    github.index_failures = 10
    monkeypatch.setattr(registration.time, "sleep", lambda _: None)
    with pytest.raises(builder.CatalogError, match="public catalog"):
        registration.verify_published(receipt, PUBLISHED_SHA, public_index(), github=github, attempts=2)
    assert github.index_reads == 2


def test_publication_does_not_accept_a_moved_source_tag(catalog, github):
    receipt = register(github)
    github.commit = "e" * 40
    github.assets[INDEX_URL] = json.dumps(public_index()).encode()
    with pytest.raises(builder.CatalogError, match="tag"):
        registration.verify_published(receipt, PUBLISHED_SHA, public_index(), github=github)


def test_cli_creates_a_receipt_and_verifies_the_index(catalog, github, monkeypatch, capsys):
    monkeypatch.setattr(registration, "GitHubApi", lambda: github)
    receipt_path = catalog / "receipt.json"
    assert registration.main(["register", "--repository", REPOSITORY, "--tag", "v0.1.0",
                              "--receipt", str(receipt_path)]) == 0
    receipt = json.loads(receipt_path.read_text())
    assert receipt["registration_path"] == "extensions/flowsteward.b1.yaml"
    expected = catalog / "expected.json"
    expected.write_text(json.dumps(public_index()))
    github.assets[INDEX_URL] = expected.read_bytes()
    assert registration.main(["verify", "--receipt", str(receipt_path), "--commit", PUBLISHED_SHA,
                              "--expected-index", str(expected)]) == 0
    assert "flowsteward.b1" in capsys.readouterr().out
