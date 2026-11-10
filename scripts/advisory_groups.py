"""Group security records using explicit advisory identity aliases."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy


def _serialized(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _event_key(ecosystem, dependency, event):
    return hashlib.sha256(
        json.dumps(
            ["security", ecosystem, dependency, event], separators=(",", ":")
        ).encode()
    ).hexdigest()


def _unique_rows(rows):
    return [
        deepcopy(value)
        for _, value in sorted({_serialized(row): row for row in rows}.items())
    ]


def _ids(finding):
    return set(finding.get("advisory_ids", [])) | {finding["event"]}


def _references(finding):
    return sorted(set(finding.get("references", [])) | {finding["url"]})


def _canonical_order(identifier):
    return (
        0
        if identifier.startswith("CVE-")
        else 1
        if identifier.startswith("GHSA-")
        else 2,
        identifier,
    )


def _group(records):
    advisory_ids = sorted(set().union(*(_ids(record) for record in records)))
    event = min(advisory_ids, key=_canonical_order)
    affected = _unique_rows(row for record in records for row in record["affected"])
    components = {(row["ecosystem"], row["dependency"]) for row in affected}
    # Also retain package identity when a source finding has no affected rows.
    components.update(
        (record["ecosystem"], record["dependency"])
        for record in records
        if not record.get("component_details")
    )
    references = sorted(set().union(*(_references(record) for record in records)))
    details = []
    legacy_keys = set()
    for record in records:
        legacy_keys.add(record["key"])
        legacy_keys.update(record.get("legacy_keys", []))
        if record.get("component_details"):
            details.extend(record["component_details"])
        else:
            details.append(
                {
                    "ecosystem": record["ecosystem"],
                    "dependency": record["dependency"],
                    "event": record["event"],
                    "details": record["details"],
                    "url": record["url"],
                    "advisory_ids": sorted(_ids(record)),
                    "references": _references(record),
                }
            )
    legacy_keys.update(
        _event_key(ecosystem, dependency, identifier)
        for ecosystem, dependency in components
        for identifier in advisory_ids
    )
    # A newly learned CVE can replace a GO/GHSA canonical event from an earlier run.
    legacy_keys.update(
        _event_key("advisory", "", identifier) for identifier in advisory_ids
    )
    return {
        "key": _event_key("advisory", "", event),
        "kind": "security",
        "ecosystem": ", ".join(sorted({ecosystem for ecosystem, _ in components})),
        "dependency": ", ".join(sorted({dependency for _, dependency in components})),
        "event": event,
        "url": min(record["url"] for record in records),
        "details": "Published vulnerability matches these declared versions/commits. "
        "Review the component-specific advisory details and affected release branches.",
        "affected": affected,
        "advisory_ids": advisory_ids,
        "references": references,
        "legacy_keys": sorted(legacy_keys),
        "component_details": _unique_rows(details),
    }


def group_security_findings(findings: list[dict]) -> list[dict]:
    """Merge connected primary/alias IDs, preserving package-specific evidence.

    ``advisory_ids`` must contain only the primary ID and explicit aliases, never
    OSV ``related`` links. Affected rows carry their own ecosystem and dependency.
    Updates retain their original content; no input dictionaries are modified.
    """
    security = [finding for finding in findings if finding["kind"] == "security"]
    parents = {}

    def root(identifier):
        parents.setdefault(identifier, identifier)
        while parents[identifier] != identifier:
            parents[identifier] = parents[parents[identifier]]
            identifier = parents[identifier]
        return identifier

    for finding in security:
        identifiers = sorted(_ids(finding))
        first = root(identifiers[0])
        for identifier in identifiers[1:]:
            parents[root(identifier)] = first

    groups = {}
    for finding in security:
        groups.setdefault(root(finding["event"]), []).append(finding)

    result = [_group(records) for records in groups.values()]
    result.extend(
        deepcopy(finding) for finding in findings if finding["kind"] != "security"
    )
    return sorted(
        result,
        key=lambda finding: (
            finding["kind"] != "security",
            finding["dependency"],
            finding["event"],
            _serialized(finding),
        ),
    )
