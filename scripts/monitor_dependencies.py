"""Monitor the catalog's published official extensions; dry-run unless opted in."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote as urlquote
from urllib.parse import urlsplit

from advisory_groups import group_security_findings
from dependency_inventory import discover, select_extensions
from dependency_sources import (
    HTTP,
    NoStableRelease,
    NotFound,
    Services,
    SourceError,
    quote,
    stable_newer,
    version_key,
)

END = "<!-- /flow-steward-dependency-monitor -->"


def safe_text(value):
    """Untrusted metadata is prose, never Markdown instructions or user mentions."""
    return re.sub(
        r"([\\`*_{}\[\]<>|])", r"\\\1", str(value).replace("@", "＠").replace("\n", " ")
    )[:500]


def event_key(kind, ecosystem, name, event):
    return hashlib.sha256(
        json.dumps([kind, ecosystem, name, event], separators=(",", ":")).encode()
    ).hexdigest()


def scan_extensions(extensions, services):
    report = {
        "schema_version": 1,
        "checked_at": datetime.now(UTC).isoformat(),
        "extensions": [],
        "findings": [],
        "errors": [],
    }
    findings = {}
    for ext in extensions:
        record = {**asdict(ext), "commit": "", "dependencies": [], "gaps": []}
        report["extensions"].append(record)
        try:
            sha, files, paths = services.source(ext)
            record["commit"] = sha
            inventory = discover(files, paths)
            try:
                loader = getattr(services, "runtime_inventory", None)
                if loader:
                    runtime_inventory = loader(ext)
                    inventory.dependencies.extend(runtime_inventory.dependencies)
                    inventory.gaps.extend(runtime_inventory.gaps)
                else:
                    inventory.gaps.append(
                        "Runtime asset inventory unavailable; binary composition not assessed"
                    )
            except (SourceError, ValueError, KeyError, TypeError) as exc:
                report["errors"].append(f"{ext.extension_id}: runtime inventory: {exc}")
                inventory.gaps.append(
                    "Runtime binary inventory unavailable; upstream declarations are not a fallback"
                )
            record["dependencies"] = [
                asdict(d) for d in sorted(set(inventory.dependencies))
            ]
            record["gaps"] = inventory.gaps
            record["gaps"].append(
                "External service/API changes and dependencies generated during builds are not inferred from source declarations."
            )
            if not inventory.dependencies:
                record["gaps"].append(
                    "No supported dependency declarations found; this does not establish absence of dependencies."
                )
        except (SourceError, ValueError, KeyError, TypeError) as exc:
            report["errors"].append(f"{ext.extension_id}: source inventory: {exc}")
            record["gaps"].append("Source inventory unavailable")
            continue
        for dep in sorted(set(inventory.dependencies)):
            if not dep.version and not dep.commit:
                continue
            affected = {
                "extension_id": ext.extension_id,
                "extension_version": ext.version,
                "repository": ext.repository,
                "commit": sha,
                "current": dep.version or dep.commit,
                "scope": dep.scope,
                "source": dep.source,
                "dependency": dep.name,
                "ecosystem": dep.ecosystem,
            }

            def finding(
                kind,
                event,
                url,
                details="",
                advisory_ids=(),
                references=(),
                dep=dep,
                affected=affected,
            ):
                key = event_key(kind, dep.ecosystem, dep.name, event)
                item = findings.setdefault(
                    key,
                    {
                        "key": key,
                        "kind": kind,
                        "ecosystem": dep.ecosystem,
                        "dependency": dep.name,
                        "event": event,
                        "url": url,
                        "details": details,
                        "affected": [],
                    },
                )
                if kind == "security":
                    item["references"] = sorted(
                        set(item.get("references", [])) | set(references)
                    )
                    item["advisory_ids"] = sorted(
                        set(item.get("advisory_ids", [])) | set(advisory_ids) | {event}
                    )
                if affected not in item["affected"]:
                    item["affected"].append(affected)

            try:
                latest = services.latest(dep)
                if dep.version and version_key(dep.version) is None:
                    record["gaps"].append(
                        f"{dep.name}: version {dep.version} cannot be ordered automatically"
                    )
                elif dep.version and stable_newer(dep.version, latest):
                    if dep.ecosystem == "GitHub":
                        url = f"https://github.com/{dep.name}/releases/tag/{quote(latest)}"
                    elif dep.ecosystem == "PyPI":
                        url = f"https://pypi.org/project/{quote(dep.name)}/{quote(latest)}/"
                    elif dep.ecosystem == "npm":
                        url = f"https://www.npmjs.com/package/{quote(dep.name)}/v/{quote(latest)}"
                    elif dep.ecosystem == "Go" and dep.name in {"stdlib", "toolchain"}:
                        url = f"https://go.dev/doc/devel/release#go{quote(latest)}"
                    else:
                        url = f"https://pkg.go.dev/{quote(dep.name)}@{quote(latest)}"
                    finding(
                        "update",
                        latest,
                        url,
                        "A newer stable version exists. Assess compatibility before changing the extension.",
                    )
            except NoStableRelease:
                record["gaps"].append(
                    f"{dep.name}: no comparable stable releases; version updates cannot be assessed"
                )
            except NotFound:
                record["gaps"].append(
                    f"{dep.name}: no public registry entry; update coverage unavailable"
                )
            except (SourceError, ValueError, KeyError, TypeError) as exc:
                report["errors"].append(
                    f"{ext.extension_id}: {dep.name}: update lookup: {exc}"
                )
            try:
                for advisory in services.vulnerabilities(dep):
                    aliases = sorted(
                        x for x in advisory.get("aliases", []) if x.startswith("CVE-")
                    )
                    event = advisory["id"]
                    fixes = sorted(
                        {
                            e["fixed"]
                            for a in advisory.get("affected", [])
                            if a.get("package", {}).get("name") == dep.name
                            and a.get("package", {}).get("ecosystem") == dep.ecosystem
                            for r in a.get("ranges", [])
                            for e in r.get("events", [])
                            if "fixed" in e
                        }
                    )
                    details = advisory.get(
                        "summary",
                        "Published vulnerability matches this declared version/commit.",
                    )
                    if aliases:
                        details += " Aliases: " + ", ".join(aliases) + "."
                    if fixes:
                        details += (
                            " Fixed versions listed by advisory: "
                            + ", ".join(fixes)
                            + ". Check the affected release branch."
                        )
                    finding(
                        "security",
                        event,
                        f"https://osv.dev/vulnerability/{quote(advisory['id'])}",
                        details,
                        advisory_ids=[advisory["id"], *advisory.get("aliases", [])],
                        references=[
                            r["url"]
                            for r in advisory.get("references", [])
                            if isinstance(r, dict)
                            and isinstance(r.get("url"), str)
                            and urlsplit(r["url"]).scheme in {"https", "http"}
                            and urlsplit(r["url"]).hostname
                            and not urlsplit(r["url"]).username
                        ],
                    )
            except (SourceError, ValueError, KeyError, TypeError) as exc:
                report["errors"].append(
                    f"{ext.extension_id}: {dep.name}: vulnerability lookup: {exc}"
                )
        record["gaps"] = sorted(set(record["gaps"]))
    report["findings"] = sorted(
        group_security_findings(list(findings.values())),
        key=lambda f: (f["kind"] != "security", f["dependency"], f["event"]),
    )
    report["errors"] = sorted(set(report["errors"]))
    return report


def issue_body(finding):
    marker = f"<!-- flow-steward-dependency-monitor:{finding['key']} -->"
    lines = [
        marker,
        f"**{safe_text(finding['dependency'])} ({safe_text(finding['ecosystem'])}) — {safe_text(finding['event'])}**",
        "",
        safe_text(finding["details"]),
        "",
        f"[Upstream evidence]({urlquote(finding['url'], safe=':/?=&%#@+~.-_')})",
        "",
        "| Extension | Published version | Dependency | Version | Scope | Source |",
        "|---|---|---|---|---|---|",
    ]
    for item in sorted(
        finding["affected"],
        key=lambda x: (x["extension_id"], x["source"], x["current"], x["scope"]),
    ):
        url = (
            item["source"].split("!/", 1)[0]
            if item["source"].startswith("https://github.com/")
            else f"https://github.com/{item['repository']}/blob/{item['commit']}/{quote(item['source'])}"
        )
        lines.append(
            f"| {safe_text(item['extension_id'])} | {safe_text(item['extension_version'])} | {safe_text(item.get('dependency', finding['dependency']))} | {safe_text(item['current'])} | {safe_text(item['scope'])} | [declaration]({url}) |"
        )
    if finding.get("advisory_ids"):
        lines += [
            "",
            "Advisory IDs: " + ", ".join(safe_text(x) for x in finding["advisory_ids"]),
        ]
    for component in finding.get("component_details", []):
        lines += [
            "",
            f"- {safe_text(component['dependency'])}: {safe_text(component['details'])} ([advisory]({urlquote(component['url'], safe=':/?=&%#@+~.-_')}))",
        ]
    if finding.get("references"):
        lines += ["", "References:"] + [
            f"- [Source {i}]({urlquote(url, safe=':/?=&%#@+~.-_')})"
            for i, url in enumerate(finding["references"], 1)
        ]
    lines += [
        "",
        "Review applicability and compatibility, update the extension where needed, run its tests, and publish a new release.",
        "This finding concerns declared versions; it does not prove exploitability in a deployed installation.",
        "Closing this issue acknowledges this event. The monitor will not reopen it. Put human notes outside this generated section.",
        END,
    ]
    return "\n".join(lines)


def sync_issues(report, services, repository, *, write=False):
    if not write:
        return {"created": 0, "updated": 0, "unchanged": 0, "dry_run": True}
    existing = {}
    for issue in services.list_issues(repository):
        if issue.get("user", {}).get("login") != "github-actions[bot]":
            continue
        match = re.search(
            r"<!-- flow-steward-dependency-monitor:([a-f0-9]{64}) -->",
            issue.get("body") or "",
        )
        if match:
            existing.setdefault(match[1], issue)
    counts = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0, "dry_run": False}
    incomplete_scan = bool(report["errors"])
    for finding in report["findings"]:
        body = issue_body(finding)
        matching = [
            existing[key]
            for key in [finding["key"], *finding.get("legacy_keys", [])]
            if key in existing
        ]
        matching = sorted(
            {i["number"]: i for i in matching}.values(),
            key=lambda i: (i["state"] != "closed", i["number"]),
        )
        issue = matching[0] if matching else None
        if issue is None:
            title = f"[dependency {finding['kind']}] {safe_text(finding['dependency'])}: {safe_text(finding['event'])}"[
                :240
            ]
            try:
                services.create_issue(repository, title, body)
                counts["created"] += 1
            except (SourceError, ValueError, KeyError, TypeError) as exc:
                report["errors"].append(
                    f"issue creation failed for {finding['dependency']} {finding['event']}: {exc}"
                )
                counts["failed"] += 1
        elif issue["state"] == "closed" or incomplete_scan:
            counts["unchanged"] += 1
        else:
            old = issue.get("body") or ""
            match = re.search(
                r"<!-- flow-steward-dependency-monitor:[a-f0-9]{64} -->", old
            )
            start = match.start() if match else -1
            end = old.find(END, start)
            if end == -1:
                report["errors"].append(
                    f"issue #{issue['number']} has an incomplete generated section; refusing to overwrite human text"
                )
                counts["failed"] += 1
                continue
            updated = old[:start] + body + old[end + len(END) :]
            if updated != old:
                try:
                    services.update_issue(repository, issue["number"], updated)
                    counts["updated"] += 1
                except (SourceError, ValueError, KeyError, TypeError) as exc:
                    report["errors"].append(
                        f"issue #{issue['number']} update failed: {exc}"
                    )
                    counts["failed"] += 1
            else:
                counts["unchanged"] += 1
    return counts


def write_reports(report, directory):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "dependency-report.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    lines = [
        "# Extension dependency monitoring",
        "",
        f"Checked at: {report['checked_at']}",
        "",
        f"Extensions: {len(report['extensions'])}; findings: {len(report['findings'])}; errors: {len(report['errors'])}.",
        "",
        "No reported vulnerabilities means no match in the queried sources, not a security certification.",
        "",
        "## Findings",
        "",
    ]
    for finding in report["findings"]:
        lines.append(
            f"- **{finding['kind']}** {safe_text(finding['dependency'])}: [{safe_text(finding['event'])}]({urlquote(finding['url'], safe=':/?=&%#@+~.-_')}) — {', '.join(sorted({safe_text(a['extension_id']) for a in finding['affected']}))}"
        )
    lines += ["", "## Coverage", ""]
    for ext in report["extensions"]:
        lines += [
            f"### {safe_text(ext['extension_id'])} {safe_text(ext['version'])}",
            "",
            f"Commit: `{ext['commit'] or 'unavailable'}`; dependency declarations: {len(ext['dependencies'])}.",
            "",
        ]
        lines += [f"- {safe_text(gap)}" for gap in ext["gaps"]]
        lines.append("")
    lines += ["## Errors", ""] + [f"- {safe_text(error)}" for error in report["errors"]]
    if report.get("issues"):
        lines += [
            "",
            "## Issue reconciliation",
            "",
            json.dumps(report["issues"], sort_keys=True),
        ]
    (directory / "dependency-report.md").write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parent.parent
    )
    parser.add_argument("--output-dir", type=Path, default=Path("dependency-report"))
    parser.add_argument("--write-issues", action="store_true")
    parser.add_argument(
        "--repository", default="Flow-Steward/extensions", help="Issue destination"
    )
    parser.add_argument(
        "--extension", action="append", help="Limit read-only smoke checks to these IDs"
    )
    args = parser.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN", "")
    if args.write_issues and (not token or args.extension):
        parser.error(
            "--write-issues requires GITHUB_TOKEN and a complete (unfiltered) catalog scan"
        )
    if args.write_issues and (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REPOSITORY") != args.repository
    ):
        parser.error(
            "issue writes must run in the destination repository's GitHub Actions workflow"
        )
    services = Services(HTTP(token))
    try:
        extensions = select_extensions(args.root)
        if args.extension:
            selected = set(args.extension)
            extensions = [e for e in extensions if e.extension_id in selected]
            if {e.extension_id for e in extensions} != selected:
                raise ValueError("unknown or unpublished extension requested")
        report = scan_extensions(extensions, services)
    except (SourceError, ValueError, KeyError, TypeError, OSError) as exc:
        report = {
            "schema_version": 1,
            "checked_at": datetime.now(UTC).isoformat(),
            "extensions": [],
            "findings": [],
            "errors": [f"catalog inventory failed: {exc}"],
        }
    write_reports(report, args.output_dir)
    try:
        report["issues"] = sync_issues(
            report, services, args.repository, write=args.write_issues
        )
    except (SourceError, ValueError, KeyError, TypeError) as exc:
        report["errors"].append(f"issue reconciliation failed: {exc}")
    write_reports(report, args.output_dir)
    print(
        f"Checked {len(report['extensions'])} extensions; {len(report['findings'])} findings; {len(report['errors'])} errors. Report: {args.output_dir}"
    )
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
