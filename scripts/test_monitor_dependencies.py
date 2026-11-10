"""External reads are faked; discovery, matching, reporting and reconciliation run."""

import json

import pytest
from dependency_inventory import Dependency, Extension
from dependency_sources import Services, SourceError, stable_newer
from monitor_dependencies import scan_extensions, sync_issues, write_reports

EXT = Extension("com.image.processing", "1.0.0", "Flow-Steward/ext-image", "v1.0.0")


class MemoryHTTP:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    def json(self, url, *, method="GET", body=None):
        self.requests.append((url, method, body))
        value = (
            self.responses[(url, json.dumps(body, sort_keys=True))]
            if body is not None
            else self.responses[url]
        )
        if isinstance(value, Exception):
            raise value
        return value

    def text(self, url):
        return self.responses[url]


def test_resolves_tag_then_reads_blobs_from_immutable_tree():
    import base64

    api = "https://api.github.com/repos/Flow-Steward/ext-image"
    http = MemoryHTTP(
        {
            f"{api}/commits/v1.0.0": {
                "sha": "a" * 40,
                "commit": {"tree": {"sha": "b" * 40}},
            },
            f"{api}/git/trees/{'b' * 40}?recursive=1": {
                "truncated": False,
                "tree": [
                    {
                        "path": "extension.yaml",
                        "type": "blob",
                        "mode": "100644",
                        "sha": "c" * 40,
                        "size": 24,
                    },
                    {
                        "path": "main.py",
                        "type": "blob",
                        "mode": "100644",
                        "sha": "d" * 40,
                    },
                ],
            },
            f"{api}/git/blobs/{'c' * 40}": {
                "encoding": "base64",
                "content": base64.b64encode(b"python_requirements: []").decode(),
            },
        }
    )
    sha, files, paths = Services(http).source(EXT)
    assert sha == "a" * 40
    assert files == {"extension.yaml": "python_requirements: []"}
    assert "main.py" in paths
    assert len(http.requests) == 3


def test_truncated_tree_is_not_a_complete_inventory():
    api = "https://api.github.com/repos/Flow-Steward/ext-image"
    http = MemoryHTTP(
        {
            f"{api}/commits/v1.0.0": {
                "sha": "a" * 40,
                "commit": {"tree": {"sha": "b" * 40}},
            },
            f"{api}/git/trees/{'b' * 40}?recursive=1": {"truncated": True, "tree": []},
        }
    )
    with pytest.raises(SourceError, match="truncated"):
        Services(http).source(EXT)


@pytest.mark.parametrize(
    "current,latest,expected",
    [
        ("1.9.0", "1.10.0", True),
        ("v1.3.0", "v1.2.9", False),
        ("2.0.0", "2.1.0rc1", False),
        ("2.0.0", "2.0.0", False),
        ("v1.0.0", "v1.1.0+incompatible", True),
    ],
)
def test_version_comparison_is_numeric_and_ignores_prereleases(
    current, latest, expected
):
    assert stable_newer(current, latest) is expected


def test_pypi_filters_yanked_empty_and_prerelease_versions_and_caches():
    url = "https://pypi.org/pypi/requests/json"
    http = MemoryHTTP(
        {
            url: {
                "releases": {
                    "2.31.0": [{"yanked": False}],
                    "2.32.0": [{"yanked": False}],
                    "3.0.0": [{"yanked": True}],
                    "4.0.0": [],
                    "5.0.0rc1": [{"yanked": False}],
                }
            }
        }
    )
    services = Services(http)
    dep = Dependency("PyPI", "requests", "2.31.0", "requirements.txt")
    assert services.latest(dep) == "2.32.0"
    assert services.latest(dep) == "2.32.0"
    assert len(http.requests) == 1


def test_osv_paginates_and_excludes_withdrawn_advisories():
    query = {"package": {"ecosystem": "PyPI", "name": "requests"}, "version": "2.31.0"}
    second = {**query, "page_token": "next"}
    url = "https://api.osv.dev/v1/query"
    http = MemoryHTTP(
        {
            (url, json.dumps(query, sort_keys=True)): {
                "vulns": [{"id": "GHSA-one"}],
                "next_page_token": "next",
            },
            (url, json.dumps(second, sort_keys=True)): {
                "vulns": [
                    {"id": "GHSA-two"},
                    {"id": "GHSA-old", "withdrawn": "2026-01-01"},
                ]
            },
        }
    )
    vulns = Services(http).vulnerabilities(
        Dependency("PyPI", "requests", "2.31.0", "requirements.txt")
    )
    assert [v["id"] for v in vulns] == ["GHSA-one", "GHSA-two"]


class FakeServices:
    def __init__(self):
        self.sources = {
            EXT.repository: {"requirements.txt": "requests==2.31.0\nhttpx>=0.27"}
        }
        self.latest_error = False

    def source(self, ext):
        files = self.sources[ext.repository]
        if isinstance(files, Exception):
            raise files
        return "a" * 40, files, list(files)

    def latest(self, dep):
        if self.latest_error:
            raise SourceError("registry unavailable")
        return "2.32.0"

    def vulnerabilities(self, dep):
        return [
            {
                "id": "GHSA-example",
                "aliases": ["CVE-2026-1234"],
                "summary": "Example advisory",
                "affected": [
                    {
                        "package": {"ecosystem": "PyPI", "name": "requests"},
                        "ranges": [
                            {"events": [{"introduced": "0"}, {"fixed": "2.32.0"}]}
                        ],
                    }
                ],
            }
        ]


def test_scan_groups_shared_dependencies_and_retains_exact_sources():
    services = FakeServices()
    ext2 = Extension("flowsteward.other", "1.1.0", "Flow-Steward/ext-other", "v1.1.0")
    services.sources[ext2.repository] = {"requirements.txt": "requests==2.31.0"}
    report = scan_extensions([EXT, ext2], services)
    assert len(report["findings"]) == 2
    assert {f["kind"] for f in report["findings"]} == {"update", "security"}
    assert all(len(f["affected"]) == 2 for f in report["findings"])
    assert report["extensions"][0]["commit"] == "a" * 40
    assert any("httpx" in g for g in report["extensions"][0]["gaps"])
    assert not report["errors"]


def test_failed_latest_lookup_does_not_hide_security_findings_or_other_extensions():
    services = FakeServices()
    services.latest_error = True
    bad = Extension("flowsteward.bad", "1.0.0", "Flow-Steward/ext-bad", "v1.0.0")
    services.sources[bad.repository] = SourceError("source unavailable")
    report = scan_extensions([bad, EXT], services)
    assert [f["kind"] for f in report["findings"]] == ["security"]
    assert len(report["errors"]) == 2
    assert len(report["extensions"]) == 2


class IssueStore:
    def __init__(self):
        self.issues = []
        self.mutations = []

    def list_issues(self, repository):
        return self.issues

    def create_issue(self, repository, title, body):
        issue = {
            "number": len(self.issues) + 1,
            "title": title,
            "body": body,
            "state": "open",
            "user": {"login": "github-actions[bot]"},
        }
        self.issues.append(issue)
        self.mutations.append(("create", issue["number"]))

    def update_issue(self, repository, number, body):
        self.issues[number - 1]["body"] = body
        self.mutations.append(("update", number))


def test_issues_are_idempotent_preserve_notes_and_respect_closed_events():
    report = scan_extensions([EXT], FakeServices())
    store = IssueStore()
    sync_issues(report, store, "Flow-Steward/extensions", write=False)
    assert not store.issues
    sync_issues(report, store, "Flow-Steward/extensions", write=True)
    assert len(store.issues) == 2
    store.issues[0]["body"] += "\nHuman investigation notes.\n"
    store.issues[1]["state"] = "closed"
    sync_issues(report, store, "Flow-Steward/extensions", write=True)
    assert store.mutations == [("create", 1), ("create", 2)]
    assert store.issues[0]["body"].endswith("Human investigation notes.\n")
    assert store.issues[1]["state"] == "closed"


def test_new_update_target_creates_new_event_and_manual_marker_cannot_suppress_it():
    report = scan_extensions([EXT], FakeServices())
    store = IssueStore()
    sync_issues(report, store, "Flow-Steward/extensions", write=True)
    store.issues[0]["user"]["login"] = "someone-else"
    sync_issues(report, store, "Flow-Steward/extensions", write=True)
    assert len(store.issues) == 3


def test_reports_expose_gaps_and_errors(tmp_path):
    report = scan_extensions([EXT], FakeServices())
    report["errors"].append("OSV unavailable")
    write_reports(report, tmp_path)
    data = json.loads((tmp_path / "dependency-report.json").read_text())
    assert data["errors"] == ["OSV unavailable"]
    summary = (tmp_path / "dependency-report.md").read_text()
    assert "httpx" in summary and "OSV unavailable" in summary
    assert "com.image.processing" in summary


def test_changed_findings_refresh_only_generated_section():
    report = scan_extensions([EXT], FakeServices())
    store = IssueStore()
    sync_issues(report, store, "Flow-Steward/extensions", write=True)
    store.issues[0]["body"] = (
        "Owner notes before.\n" + store.issues[0]["body"] + "\nNotes after."
    )
    report["findings"][0]["affected"][0]["extension_version"] = "1.0.1"
    sync_issues(report, store, "Flow-Steward/extensions", write=True)
    assert ("update", 1) in store.mutations
    assert store.issues[0]["body"].startswith("Owner notes before.\n")
    assert store.issues[0]["body"].endswith("\nNotes after.")
    assert "1.0.1" in store.issues[0]["body"]


def test_new_release_event_gets_new_issue_after_prior_release_closed():
    report = scan_extensions([EXT], FakeServices())
    store = IssueStore()
    sync_issues(report, store, "Flow-Steward/extensions", write=True)
    for issue in store.issues:
        issue["state"] = "closed"
    services = FakeServices()
    services.latest = lambda dep: "2.33.0"
    sync_issues(
        scan_extensions([EXT], services), store, "Flow-Steward/extensions", write=True
    )
    assert len(store.issues) == 3
    assert "2.33.0" in store.issues[-1]["title"]


def test_github_issue_pagination_includes_closed_and_excludes_pull_requests():
    base = "https://api.github.com/repos/Flow-Steward/extensions/issues?state=all&per_page=100&page="
    http = MemoryHTTP(
        {
            base + "1": [{"number": i} for i in range(100)],
            base + "2": [
                {"number": 101, "state": "closed"},
                {"number": 102, "pull_request": {}},
            ],
        }
    )
    issues = Services(http).list_issues("Flow-Steward/extensions")
    assert len(issues) == 101
    assert issues[-1] == {"number": 101, "state": "closed"}


def test_token_is_only_sent_to_github_and_untrusted_hosts_are_rejected():
    import io

    from dependency_sources import HTTP

    class Capture:
        def __init__(self):
            self.requests = []

        def open(self, request, timeout):
            self.requests.append(request)
            return io.BytesIO(b"{}")

    client = HTTP("test-secret")
    client.opener = Capture()
    client.json("https://api.github.com/repos/Flow-Steward/extensions")
    client.json(
        "https://api.osv.dev/v1/query", method="POST", body={"commit": "a" * 40}
    )
    assert client.opener.requests[0].get_header("Authorization") == "Bearer test-secret"
    assert client.opener.requests[1].get_header("Authorization") is None
    with pytest.raises(SourceError, match="unsupported"):
        client.json("https://api.github.com.evil.test/steal")
    assert len(client.opener.requests) == 2


def test_issue_write_failure_is_reported_and_exits_nonzero(tmp_path, monkeypatch):
    import monitor_dependencies as monitor

    class FailingWriter(FakeServices):
        def list_issues(self, repository):
            return []

        def create_issue(self, repository, title, body):
            raise SourceError("write denied")

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "Flow-Steward/extensions")
    monkeypatch.setattr(monitor, "select_extensions", lambda root: [EXT])
    monkeypatch.setattr(monitor, "Services", lambda http: FailingWriter())
    code = monitor.main(["--write-issues", "--output-dir", str(tmp_path)])
    assert code == 1
    report = json.loads((tmp_path / "dependency-report.json").read_text())
    assert len(report["findings"]) == 2
    assert any("write denied" in error for error in report["errors"])


def test_upstream_commit_queries_osv_without_version():
    query = {"commit": "a" * 40}
    url = "https://api.osv.dev/v1/query"
    http = MemoryHTTP({(url, json.dumps(query, sort_keys=True)): {"vulns": []}})
    assert (
        Services(http).vulnerabilities(
            Dependency(
                "GitHub",
                "googleapis/mcp-toolbox",
                "v1.3.0",
                "toolbox-provenance.json",
                commit="a" * 40,
            )
        )
        == []
    )


def test_http_redirects_are_not_followed_with_token():
    from dependency_sources import NoRedirect

    with pytest.raises(SourceError, match="redirected"):
        NoRedirect().redirect_request(None, None, 302, "moved", {}, "https://evil.test")


def test_new_cve_alias_does_not_recreate_an_acknowledged_advisory():
    services = FakeServices()
    original = services.vulnerabilities
    services.vulnerabilities = lambda dep: [{**v, "aliases": []} for v in original(dep)]
    store = IssueStore()
    sync_issues(
        scan_extensions([EXT], services), store, "Flow-Steward/extensions", write=True
    )
    for issue in store.issues:
        issue["state"] = "closed"
    services.vulnerabilities = original
    sync_issues(
        scan_extensions([EXT], services), store, "Flow-Steward/extensions", write=True
    )
    assert len(store.issues) == 2


def test_partial_scan_preserves_previous_affected_extensions():
    services = FakeServices()
    ext2 = Extension("flowsteward.other", "1.0.0", "Flow-Steward/ext-other", "v1.0.0")
    services.sources[ext2.repository] = {"requirements.txt": "requests==2.31.0"}
    store = IssueStore()
    sync_issues(
        scan_extensions([EXT, ext2], services),
        store,
        "Flow-Steward/extensions",
        write=True,
    )
    services.sources[ext2.repository] = SourceError("cannot read source")
    sync_issues(
        scan_extensions([EXT, ext2], services),
        store,
        "Flow-Steward/extensions",
        write=True,
    )
    assert all("flowsteward.other" in i["body"] for i in store.issues)


def test_damaged_issue_marker_does_not_block_other_new_findings():
    import monitor_dependencies as monitor

    report = scan_extensions([EXT], FakeServices())
    store = IssueStore()
    only_first = {**report, "findings": report["findings"][:1]}
    sync_issues(only_first, store, "Flow-Steward/extensions", write=True)
    store.issues[0]["body"] = store.issues[0]["body"].replace(monitor.END, "")
    sync_issues(report, store, "Flow-Steward/extensions", write=True)
    assert len(store.issues) == 2
    assert any("incomplete" in e for e in report["errors"])


def test_failed_issue_write_does_not_hide_later_findings():
    class OneFailure(IssueStore):
        def create_issue(self, repository, title, body):
            if "security" in title:
                raise SourceError("temporary failure")
            return super().create_issue(repository, title, body)

    report = scan_extensions([EXT], FakeServices())
    store = OneFailure()
    counts = sync_issues(report, store, "Flow-Steward/extensions", write=True)
    assert len(store.issues) == 1 and "update" in store.issues[0]["title"]
    assert counts["failed"] == 1
    assert any("temporary failure" in e for e in report["errors"])


def test_github_mutations_are_spaced_without_delaying_osv_queries(monkeypatch):
    import io

    import dependency_sources as sources

    waits = []
    monkeypatch.setattr(sources.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(sources.time, "sleep", waits.append)

    class Responder:
        def open(self, request, timeout):
            return io.BytesIO(b"{}")

    client = sources.HTTP("test-token")
    client.opener = Responder()
    url = "https://api.github.com/repos/Flow-Steward/extensions/issues"
    client.json(url, method="POST", body={"title": "first"})
    client.json(
        "https://api.osv.dev/v1/query", method="POST", body={"commit": "a" * 40}
    )
    assert waits == []
    client.json(url, method="POST", body={"title": "second"})
    assert len(waits) == 1 and waits[0] >= 1


def test_go_module_without_stable_releases_is_a_coverage_gap_not_outage():
    class GoOnly(FakeServices):
        def __init__(self):
            self.sources = {
                EXT.repository: {
                    "go.mod": "module example.org/app\nrequire golang.org/x/exp v0.0.0-20260101120000-abcdefabcdef\n"
                }
            }
            self.registries = Services(
                MemoryHTTP({"https://proxy.golang.org/golang.org/x/exp/@v/list": ""})
            )

        def latest(self, dep):
            return self.registries.latest(dep)

        def vulnerabilities(self, dep):
            return []

    report = scan_extensions([EXT], GoOnly())
    assert not report["errors"]
    assert any("stable" in gap for gap in report["extensions"][0]["gaps"])
