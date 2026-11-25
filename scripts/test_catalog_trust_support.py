"""Release-specific trust and registered first-party Support publication contracts."""

import json
from pathlib import Path

import pytest
import yaml

import build_index as builder
from catalog_test_helpers import _support as support_files
from test_build_index import CATEGORIES, FakeGitHub, _commit, _entry, _manifest, _zip
from test_build_index import repo as repo

CURATED = {
    "flowsteward.shopify": ("ext-ecommerce-shopify", "0.5.5"),
    "flowsteward.data-connector-mcp-toolbox-mysql": ("ext-data-mysql", "1.3.12"),
    "flowsteward.data-connector-mcp-toolbox-postgres": ("ext-data-postgres", "1.4.14"),
    "flowsteward.google-workspace": ("ext-productivity-google-workspace", "0.3.7"),
    "flowsteward.telegram": ("ext-messaging-telegram", "1.3.5"),
    "flowsteward.whatsapp": ("ext-messaging-whatsapp", "0.1.4"),
    "flowsteward.docling": ("ext-document-docling", "0.3.7"),
    "flowsteward.example-showcase": ("ext-example-showcase", "1.2.8"),
    "flowsteward.file-transfer": ("ext-file-transfer-sftp", "0.3.10"),
    "flowsteward.imap-mailbox": ("ext-email-imap", "0.2.5"),
    "flowsteward.openrouter": ("ext-llm-openrouter", "1.2.4"),
    "flowsteward.ollama-remote": ("ext-llm-ollama", "1.2.4"),
    "flowsteward.outgoing-email": ("ext-email-smtp", "0.3.5"),
    "flowsteward.typesafe-ai": ("ext-typesafe-ai", "1.0.9"),
    "flowsteward.web-scraper": ("ext-data-web-scraper", "0.1.29"),
    "com.image.processing": ("ext-image-processing", "0.2.9"),
    "com.discogs.api": ("ext-discogs", "0.2.7"),
    "flowsteward.microsoft-365": ("ext-productivity-microsoft-365", "0.2.7"),
    "flowsteward.wordpress-woocommerce": ("ext-cms-wordpress-woocommerce", "1.2.6"),
    "flowsteward.gotenberg": ("ext-document-gotenberg", "0.1.0"),
    "flowsteward.discord": ("ext-messaging-discord", "0.1.5"),
}
REPOSITORY = "https://github.com/Flow-Steward/ext-example"


def _first_party_manifest(
    extension_id="flowsteward.example", version="1.0.0", repository=REPOSITORY
):
    return _manifest(
        extension_id=extension_id,
        version=version,
        ui_manifest="ui/ui_manifest.yaml",
        vendor={"support_url": f"{repository}/issues"},
    )


def _inspect(manifest, extra, repository=REPOSITORY):
    extension_id = manifest["extension_id"]
    return builder.inspect_archive(
        _zip(manifest, top=builder.folder_name(extension_id), extra=extra),
        entry=builder.parse_entry(extension_id, f"repository: {repository}\n"),
        version=manifest["version"],
        categories=set(CATEGORIES),
        publishers={"flowsteward": "Flow-Steward"},
    )


def test_namespace_authorization_does_not_grant_verification(repo):
    item = _inspect(_first_party_manifest(), support_files(REPOSITORY))
    assert item["verification_status"] == "unverified"
    unauthorized = builder.parse_entry(
        "flowsteward.example", "repository: https://github.com/other/ext-example\n"
    )
    assert "reserved" in builder.namespace_problem(
        unauthorized, builder.verified_publishers()
    )


@pytest.mark.parametrize("extension_id", CURATED)
def test_curated_release_survives_publish_and_index_without_mutating_records(
    repo, extension_id
):
    name, version = CURATED[extension_id]
    repository = f"https://github.com/Flow-Steward/{name}"
    policy = {
        extension_id: {
            "repository": repository,
            "version": version,
            "reason": "Selected by the maintainer as a tested integration.",
        }
    }
    (repo / "verified_extensions.json").write_text(json.dumps(policy))
    manifest = _first_party_manifest(extension_id, version, repository)
    data = _zip(
        manifest, top=builder.folder_name(extension_id), extra=support_files(repository)
    )
    github = FakeGitHub()
    github.release(f"Flow-Steward/{name}", version, data, extension_id=extension_id)
    _entry(repo, extension_id, repository)
    assert not builder.publish(github=github).problems
    _commit(repo, "record")
    record_path = builder.record_path(extension_id, version)
    before = record_path.read_bytes()
    assert builder.build_index()["items"][0]["verification_status"] == "verified"
    assert record_path.read_bytes() == before
    for changes in (
        {"version": "99.0.0"},
        {"repository": "https://github.com/Flow-Steward/ext-other"},
    ):
        (repo / "verified_extensions.json").write_text(
            json.dumps({extension_id: {**policy[extension_id], **changes}})
        )
        assert builder.build_index()["items"][0]["verification_status"] == "unverified"
        assert record_path.read_bytes() == before


def test_old_namespace_verified_records_are_projected_unverified_without_rewriting(
    repo,
):
    extension_id = "flowsteward.example"
    record = {
        "extension_id": extension_id,
        "version": "1.0.0",
        "repository": REPOSITORY,
        "tag": "v1.0.0",
        "host_contract": builder.HOST_CONTRACT,
        "published_at": "2026-11-18T00:00:00Z",
        "icon": {
            "path": builder.icon_path(extension_id, "1.0.0"),
            "sha256": "a" * 64,
            "bytes": 1,
            "mime_type": "image/png",
            "size": "128x128",
        },
        "item": {
            "extension_id": extension_id,
            "version": "1.0.0",
            "name": "Example",
            "verification_status": "verified",
            "repository_url": f"{REPOSITORY}/tree/v1.0.0",
        },
    }
    builder.write_record(record)
    _commit(repo, "legacy record")
    path = builder.record_path(extension_id, "1.0.0")
    before = path.read_bytes()
    assert builder.build_index()["items"][0]["verification_status"] == "unverified"
    assert path.read_bytes() == before


def test_checked_in_curation_is_exactly_the_designated_releases():
    policy = json.loads(
        (Path(__file__).resolve().parents[1] / "verified_extensions.json").read_text()
    )
    assert {
        key: (value["repository"], value["version"]) for key, value in policy.items()
    } == {
        key: (f"https://github.com/Flow-Steward/{repo}", version)
        for key, (repo, version) in CURATED.items()
    }


@pytest.mark.parametrize(
    "raw",
    [
        [],
        {"bad": {}},
        {
            "flowsteward.example": {
                "repository": REPOSITORY,
                "version": "latest",
                "reason": "tested",
            }
        },
        {
            "flowsteward.example": {
                "repository": REPOSITORY,
                "version": "1.0.0",
                "reason": "",
                "verified": True,
            }
        },
        {
            "flowsteward.example": {
                "repository": "https://evil.test/Flow-Steward/ext-example",
                "version": "1.0.0",
                "reason": "tested",
            }
        },
    ],
)
def test_malformed_curation_fails_clearly(repo, raw):
    (repo / "verified_extensions.json").write_text(json.dumps(raw))
    with pytest.raises(builder.CatalogError, match="verified_extensions.json"):
        builder.build_index()


def test_invalid_json_curation_fails_clearly(repo):
    (repo / "verified_extensions.json").write_text("{")
    with pytest.raises(builder.CatalogError, match="verified_extensions.json"):
        builder.build_index()


@pytest.mark.parametrize("style", ["inline", "refs", "content"])
def test_registered_global_support_accepts_existing_content_styles(repo, style):
    assert (
        _inspect(_first_party_manifest(), support_files(REPOSITORY, style=style))[
            "extension_id"
        ]
        == "flowsteward.example"
    )


@pytest.mark.parametrize(
    "broken",
    [
        "missing_manifest",
        "unregistered",
        "missing_page",
        "project_scoped",
        "missing_component",
        "escape",
        "wrong_repo",
        "missing_issues_link",
        "wrong_vendor",
        "non_markdown",
        "malformed_page",
    ],
)
def test_broken_first_party_support_is_rejected(repo, broken):
    manifest, files = _first_party_manifest(), support_files(REPOSITORY, style="refs")
    if broken == "missing_manifest":
        manifest.pop("ui_manifest")
    elif broken == "unregistered":
        files["ui/ui_manifest.yaml"] = "version: '1'\npages: []\n"
    elif broken == "missing_page":
        files.pop("ui/pages/support.yaml")
    elif broken == "project_scoped":
        files["ui/pages/support.yaml"] = files["ui/pages/support.yaml"].replace(
            "project_scoped: false", "project_scoped: true"
        )
    elif broken == "missing_component":
        files.pop("ui/components/contact.yaml")
    elif broken == "escape":
        files["ui/pages/support.yaml"] = files["ui/pages/support.yaml"].replace(
            "../components/contact.yaml", "../../../contact.yaml"
        )
    elif broken == "wrong_repo":
        files = support_files("https://github.com/Flow-Steward/ext-other")
    elif broken == "missing_issues_link":
        files["ui/components/contact.yaml"] = yaml.safe_dump(
            {
                "component_id": "contact",
                "type": "markdown",
                "body": f"[Report]({REPOSITORY}/issues/new/choose)",
            }
        )
    elif broken == "wrong_vendor":
        manifest["vendor"]["support_url"] = (
            "https://github.com/Flow-Steward/ext-other/issues"
        )
    elif broken == "non_markdown":
        files["ui/components/contact.yaml"] = files[
            "ui/components/contact.yaml"
        ].replace("type: markdown", "type: text")
    else:
        files["ui/pages/support.yaml"] = "[]"
    with pytest.raises(builder.CatalogError, match="Support"):
        _inspect(manifest, files)


def test_external_author_is_not_subject_to_first_party_support_policy(repo):
    assert (
        _inspect(_manifest(), {}, "https://github.com/acme/mailbox-extension")[
            "verification_status"
        ]
        == "unverified"
    )


def test_unchanged_old_release_recheck_does_not_apply_new_support_policy(repo):
    github = FakeGitHub()
    manifest = _manifest(extension_id="flowsteward.example")
    data = _zip(manifest, top="flowsteward_example")
    url = github.release(
        "Flow-Steward/ext-example", "1.0.0", data, extension_id="flowsteward.example"
    )
    import hashlib

    record = {
        "extension_id": "flowsteward.example",
        "version": "1.0.0",
        "repository": REPOSITORY,
        "host_contract": builder.HOST_CONTRACT,
        "published_at": "2026-11-18T00:00:00Z",
        "item": {
            "release_zip_url": url,
            "release_zip_sha256": hashlib.sha256(data).hexdigest(),
        },
    }
    builder.write_record(record)
    _entry(repo, "flowsteward.example", REPOSITORY)
    path = builder.record_path("flowsteward.example", "1.0.0")
    before = path.read_bytes()
    assert builder.publish(github=github) == builder.PublishReport([], [], [])
    assert path.read_bytes() == before


@pytest.mark.parametrize("vendor", [None, {}, {"name": "Flow Steward"}])
def test_root_support_url_alias_matches_host_manifest_normalization(repo, vendor):
    manifest = _first_party_manifest()
    manifest["support_url"] = manifest["vendor"]["support_url"]
    manifest["vendor_name"] = "Flow Steward"
    if vendor is None:
        manifest.pop("vendor")
    else:
        manifest["vendor"] = vendor
    assert (
        _inspect(manifest, support_files(REPOSITORY))["verification_status"]
        == "unverified"
    )


def test_page_metadata_urls_cannot_substitute_for_rendered_support(repo):
    files = support_files(REPOSITORY)
    files["ui/pages/support.yaml"] = yaml.safe_dump(
        {
            "page_id": "support",
            "title": "Support",
            "project_scoped": False,
            "type": "markdown",
            "content": f"{REPOSITORY}/issues {REPOSITORY}/issues/new/choose",
        }
    )
    with pytest.raises(builder.CatalogError, match="Support"):
        _inspect(_first_party_manifest(), files)


@pytest.mark.parametrize(
    "text",
    [
        f"{REPOSITORY}/issues {REPOSITORY}/issues/new/choose",
        f"```markdown\n[Issues]({REPOSITORY}/issues) [Report]({REPOSITORY}/issues/new/choose)\n```",
        f"`[Issues]({REPOSITORY}/issues)` `[Report]({REPOSITORY}/issues/new/choose)`",
        f"![Issues]({REPOSITORY}/issues) ![Report]({REPOSITORY}/issues/new/choose)",
    ],
)
def test_non_actionable_url_mentions_do_not_provide_support(repo, text):
    files = support_files(REPOSITORY)
    page = yaml.safe_load(files["ui/pages/support.yaml"])
    page["components"][0]["body"] = text
    files["ui/pages/support.yaml"] = yaml.safe_dump(page)
    with pytest.raises(builder.CatalogError, match="Support"):
        _inspect(_first_party_manifest(), files)


def test_rendered_content_takes_precedence_over_hidden_body(repo):
    files = support_files(REPOSITORY)
    page = yaml.safe_load(files["ui/pages/support.yaml"])
    page["components"][0]["content"] = "Support is unavailable."
    files["ui/pages/support.yaml"] = yaml.safe_dump(page)
    with pytest.raises(builder.CatalogError, match="Support"):
        _inspect(_first_party_manifest(), files)


def test_missing_support_is_refused_at_publication_and_submission_boundaries(repo):
    manifest = _manifest(extension_id="flowsteward.example")
    github = FakeGitHub()
    github.release(
        "Flow-Steward/ext-example",
        "1.0.0",
        _zip(manifest, top="flowsteward_example"),
        extension_id="flowsteward.example",
    )
    _entry(repo, "flowsteward.example", REPOSITORY)
    report = builder.publish(github=github)
    assert not report.recorded
    assert any("Support" in problem for problem in report.problems)
    entry = builder.parse_entry("flowsteward.example", f"repository: {REPOSITORY}\n")
    with pytest.raises(builder.CatalogError, match="Support"):
        builder._check_new_entry(
            entry,
            submitter="Flow-Steward",
            github=github,
            categories=set(CATEGORIES),
            publishers=builder.verified_publishers(),
        )
    assert not builder.record_path("flowsteward.example", "1.0.0").exists()


def test_code_spans_cannot_synthesize_a_different_markdown_destination(repo):
    files = support_files(REPOSITORY)
    page = yaml.safe_load(files["ui/pages/support.yaml"])
    page["components"][0]["body"] = (
        f"[Issues]({REPOSITORY}/issues`x`)\n[Report]({REPOSITORY}/issues/new/choose)"
    )
    files["ui/pages/support.yaml"] = yaml.safe_dump(page)
    with pytest.raises(builder.CatalogError, match="Support"):
        _inspect(_first_party_manifest(), files)


def test_component_ref_chain_does_not_provide_host_rendered_support(repo):
    files = support_files(REPOSITORY, style="refs")
    files["ui/components/contact_actual.yaml"] = files["ui/components/contact.yaml"]
    files["ui/components/contact.yaml"] = "ref: contact_actual.yaml\n"
    with pytest.raises(builder.CatalogError, match="Support"):
        _inspect(_first_party_manifest(), files)
