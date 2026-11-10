"""Runtime composition and alias migration must change actual emitted issues."""

import json

import pytest
from dependency_inventory import Dependency, Extension, Inventory, select_extensions
from dependency_sources import SourceError
from monitor_dependencies import event_key, scan_extensions, sync_issues
from test_monitor_dependencies import FakeServices, IssueStore


class RuntimeServices(FakeServices):
    def __init__(self):
        self.sources = {
            "Flow-Steward/ext-postgres": {
                "toolbox-provenance.json": json.dumps(
                    {
                        "source": "https://github.com/googleapis/mcp-toolbox",
                        "upstream_tag": "v1.3.0",
                        "upstream_commit": "a" * 40,
                    }
                )
            },
            "Flow-Steward/ext-snowflake": {"extension.yaml": "python_requirements: []"},
        }

    def runtime_inventory(self, ext):
        if ext.repository.endswith("snowflake"):
            return Inventory(
                [
                    Dependency(
                        "Go",
                        "github.com/snowflakedb/gosnowflake/v2",
                        "v2.0.2",
                        "https://github.com/Flow-Steward/ext-snowflake/releases/download/v1.0.0/a.zip!/bin/linux-amd64/toolbox",
                        "runtime:linux-amd64",
                    )
                ],
                [],
            )
        return Inventory([], [])

    def upstream_go_mod(self, repository, commit):
        raise AssertionError(
            "upstream go.mod must not substitute for shipped binary modules"
        )

    def latest(self, dep):
        return dep.version

    def vulnerabilities(self, dep):
        if dep.ecosystem != "Go":
            return []
        return [
            {
                "id": "GHSA-example",
                "aliases": ["CVE-2026-1234"],
                "summary": "Driver log leak",
            }
        ]


def test_native_driver_only_affects_extension_whose_binary_contains_it():
    pg = Extension("fs.pg", "1.0.0", "Flow-Steward/ext-postgres", "v1.0.0")
    snow = Extension("fs.snow", "1.0.0", "Flow-Steward/ext-snowflake", "v1.0.0")
    report = scan_extensions([pg, snow], RuntimeServices())
    assert not report["errors"]
    assert len(report["findings"]) == 1
    finding = report["findings"][0]
    assert {a["extension_id"] for a in finding["affected"]} == {"fs.snow"}
    assert finding["advisory_ids"] == ["CVE-2026-1234", "GHSA-example"]
    assert (
        finding["affected"][0]["dependency"] == "github.com/snowflakedb/gosnowflake/v2"
    )


def test_failed_runtime_inventory_is_visible_and_never_uses_upstream_fallback():
    services = RuntimeServices()

    def unavailable(ext):
        raise SourceError("asset hash mismatch")

    services.runtime_inventory = unavailable
    ext = Extension("fs.pg", "1.0.0", "Flow-Steward/ext-postgres", "v1.0.0")
    report = scan_extensions([ext], services)
    assert any("asset hash mismatch" in e for e in report["errors"])
    assert any("runtime" in gap.lower() for gap in report["extensions"][0]["gaps"])


def test_legacy_closed_osv_issue_is_not_recreated_with_new_cve_canonical_key():
    services = RuntimeServices()
    ext = Extension("fs.snow", "1.0.0", "Flow-Steward/ext-snowflake", "v1.0.0")
    report = scan_extensions([ext], services)
    assert len(report["findings"]) == 1
    legacy = event_key(
        "security", "Go", "github.com/snowflakedb/gosnowflake/v2", "GHSA-example"
    )
    store = IssueStore()
    store.issues = [
        {
            "number": 1,
            "state": "closed",
            "user": {"login": "github-actions[bot]"},
            "body": f"<!-- flow-steward-dependency-monitor:{legacy} -->\nLegacy ack\n<!-- /flow-steward-dependency-monitor -->",
        }
    ]
    sync_issues(report, store, "Flow-Steward/extensions", write=True)
    assert len(store.issues) == 1 and store.mutations == []


def test_legacy_open_marker_is_migrated_without_overwriting_human_notes():
    services = RuntimeServices()
    ext = Extension("fs.snow", "1.0.0", "Flow-Steward/ext-snowflake", "v1.0.0")
    report = scan_extensions([ext], services)
    legacy = event_key(
        "security", "Go", "github.com/snowflakedb/gosnowflake/v2", "GHSA-example"
    )
    store = IssueStore()
    store.issues = [
        {
            "number": 1,
            "state": "open",
            "user": {"login": "github-actions[bot]"},
            "body": f"Notes before\n<!-- flow-steward-dependency-monitor:{legacy} -->\nOld\n<!-- /flow-steward-dependency-monitor -->\nNotes after",
        }
    ]
    sync_issues(report, store, "Flow-Steward/extensions", write=True)
    assert len(store.issues) == 1 and store.mutations == [("update", 1)]
    assert store.issues[0]["body"].startswith("Notes before\n")
    assert store.issues[0]["body"].endswith("\nNotes after")
    assert "CVE-2026-1234" in store.issues[0]["body"]


def test_select_extensions_carries_verified_release_asset_coordinates(tmp_path):
    (tmp_path / "extensions").mkdir()
    (tmp_path / "extensions/fs.test.yaml").write_text(
        "repository: https://github.com/Flow-Steward/ext-test\n"
    )
    url = "https://github.com/Flow-Steward/ext-test/releases/download/v1.0.0/fs.test-1.0.0-linux-amd64.zip"
    item = {
        "extension_id": "fs.test",
        "version": "1.0.0",
        "publication_status": "published",
        "repository_url": "https://github.com/Flow-Steward/ext-test/tree/v1.0.0",
        "release_targets": {
            "linux-amd64": {
                "release_zip_url": url,
                "release_zip_sha256": "a" * 64,
                "release_zip_bytes": 123,
            }
        },
    }
    (tmp_path / "index.json").write_text(json.dumps({"items": [item]}))
    assert select_extensions(tmp_path)[0].assets == (
        ("linux-amd64", url, "a" * 64, 123),
    )
    item["release_targets"]["linux-amd64"]["release_zip_url"] = (
        "https://example.test/other.zip"
    )
    (tmp_path / "index.json").write_text(json.dumps({"items": [item]}))
    with pytest.raises(ValueError, match="asset"):
        select_extensions(tmp_path)


def test_runtime_asset_transport_does_not_forward_github_api_credentials(monkeypatch):
    import io
    from urllib import request

    from dependency_sources import HTTP

    seen = []

    class Opener:
        def open(self, req, timeout):
            seen.append(req)
            return io.BytesIO(b"zip")

    monkeypatch.setattr(request, "build_opener", lambda *args: Opener())
    assert (
        HTTP("private-api-token").download(
            "https://github.com/Flow-Steward/ext-test/releases/download/v1/a.zip",
            max_bytes=3,
        )
        == b"zip"
    )
    assert seen[0].get_header("Authorization") is None


def test_release_redirect_rejects_untrusted_destinations():
    from urllib.request import Request

    from dependency_sources import ReleaseRedirect

    handler = ReleaseRedirect()
    with pytest.raises(SourceError, match="unsupported"):
        handler.redirect_request(
            Request(
                "https://github.com/Flow-Steward/ext-test/releases/download/v1/a.zip"
            ),
            None,
            302,
            "moved",
            {},
            "https://evil.test/asset",
        )


def test_go_standard_library_updates_use_official_go_release_metadata():
    from dependency_sources import Services
    from test_monitor_dependencies import MemoryHTTP

    http = MemoryHTTP(
        {
            "https://go.dev/dl/?mode=json": [
                {"version": "go1.26.5", "stable": True},
                {"version": "go1.27rc1", "stable": False},
            ]
        }
    )
    assert (
        Services(http).latest(Dependency("Go", "stdlib", "1.26.2", "binary"))
        == "1.26.5"
    )


def test_security_references_survive_scan_grouping_and_issue_rendering():
    from monitor_dependencies import issue_body

    services = RuntimeServices()
    services.vulnerabilities = lambda dep: (
        [
            {
                "id": "GHSA-example",
                "aliases": ["CVE-2026-1234"],
                "references": [
                    {
                        "type": "FIX",
                        "url": "https://github.com/vendor/driver/commit/abc",
                    }
                ],
            }
        ]
        if dep.ecosystem == "Go"
        else []
    )
    ext = Extension("fs.snow", "1.0.0", "Flow-Steward/ext-snowflake", "v1.0.0")
    finding = scan_extensions([ext], services)["findings"][0]
    assert "https://github.com/vendor/driver/commit/abc" in finding["references"]
    body = issue_body(finding)
    assert "https://github.com/vendor/driver/commit/abc" in body
    assert "https://osv.dev/vulnerability/GHSA-example" in body


def test_go_standard_library_update_links_to_official_release_notes():
    services = RuntimeServices()
    services.runtime_inventory = lambda ext: Inventory(
        [Dependency("Go", "stdlib", "1.26.2", "binary", "runtime:linux-amd64")], []
    )
    services.latest = lambda dep: "1.26.5"
    services.vulnerabilities = lambda dep: []
    ext = Extension("fs.snow", "1.0.0", "Flow-Steward/ext-snowflake", "v1.0.0")
    finding = next(
        f
        for f in scan_extensions([ext], services)["findings"]
        if f["dependency"] == "stdlib"
    )
    assert finding["url"] == "https://go.dev/doc/devel/release#go1.26.5"
