"""Advisory identity crosses package boundaries only through published aliases."""

import hashlib
import itertools
import json
from copy import deepcopy

from advisory_groups import group_security_findings


def key(ecosystem, dependency, event):
    return hashlib.sha256(
        json.dumps(
            ["security", ecosystem, dependency, event], separators=(",", ":")
        ).encode()
    ).hexdigest()


def finding(event, aliases=(), dependency="example.org/one", ecosystem="Go", **kwargs):
    return {
        "key": key(ecosystem, dependency, event),
        "kind": "security",
        "ecosystem": ecosystem,
        "dependency": dependency,
        "event": event,
        "url": f"https://osv.dev/vulnerability/{event}",
        "details": "Published vulnerability.",
        "advisory_ids": [event, *aliases],
        "affected": [
            {
                "dependency": dependency,
                "ecosystem": ecosystem,
                "extension_id": "com.example.extension",
                "extension_version": "1.0.0",
                "repository": "example/extension",
                "commit": "a" * 40,
                "current": "1.0.0",
                "source": "go.mod",
                "scope": "direct",
            }
        ],
        **kwargs,
    }


def test_shared_cve_merges_different_go_modules_and_preserves_legacy_keys():
    first = finding("GO-2026-1000", ["CVE-2026-1000"], "golang.org/x/crypto")
    second = finding("GHSA-abcd-efgh-ijkl", ["CVE-2026-1000"], "golang.org/x/net")

    [grouped] = group_security_findings([first, second])

    assert grouped["event"] == "CVE-2026-1000"
    assert grouped["key"] == key("advisory", "", "CVE-2026-1000")
    assert grouped["advisory_ids"] == [
        "CVE-2026-1000",
        "GHSA-abcd-efgh-ijkl",
        "GO-2026-1000",
    ]
    assert {row["dependency"] for row in grouped["affected"]} == {
        "golang.org/x/crypto",
        "golang.org/x/net",
    }
    expected_keys = {
        key("Go", dependency, event)
        for dependency in ("golang.org/x/crypto", "golang.org/x/net")
        for event in grouped["advisory_ids"]
    }
    expected_keys.update(
        key("advisory", "", event) for event in grouped["advisory_ids"]
    )
    assert set(grouped["legacy_keys"]) == expected_keys
    assert grouped["references"] == sorted([first["url"], second["url"]])


def test_alias_transitive_chain_and_cycle_merge_all_records():
    records = [
        finding("OSV-one", ["GHSA-one"]),
        finding("GHSA-one", ["GO-two"], "example.org/two"),
        finding("GO-two", ["CVE-2026-9999", "OSV-one"], "example.org/three"),
    ]
    [grouped] = group_security_findings(records)
    assert grouped["event"] == "CVE-2026-9999"
    assert len(grouped["affected"]) == 3
    assert set(grouped["advisory_ids"]) == {
        "OSV-one",
        "GHSA-one",
        "GO-two",
        "CVE-2026-9999",
    }


def test_order_invariance_including_alias_reference_and_affected_order():
    first = finding("OSV-one", ["GHSA-one", "CVE-2026-9999"])
    first["affected"].append({**first["affected"][0], "source": "other/go.mod"})
    first["references"] = ["https://example.org/two", "https://example.org/one"]
    records = [
        first,
        finding("GHSA-one", dependency="example.org/two"),
        finding("OSV-distinct"),
    ]
    expected = group_security_findings(records)
    for order in itertools.permutations(records):
        reordered = deepcopy(order)
        for record in reordered:
            record["advisory_ids"].reverse()
            record["affected"].reverse()
            record.get("references", []).reverse()
        assert group_security_findings(reordered) == expected


def test_distinct_cves_stay_separate_despite_same_description_and_related_links():
    first = finding("CVE-2026-1000", related=["CVE-2026-2000"])
    second = finding("CVE-2026-2000", related=["CVE-2026-1000"])
    assert len(group_security_findings([first, second])) == 2


def test_canonical_event_prefers_cve_then_ghsa_then_lexical_other():
    records = [
        finding("OSV-one", ["GO-one", "GHSA-two", "GHSA-one"]),
        finding("OSV-three", ["OSV-two"]),
        finding("OSV-four", ["CVE-2026-2222", "CVE-2026-1111", "GHSA-four"]),
    ]
    assert {item["event"] for item in group_security_findings(records)} == {
        "GHSA-one",
        "OSV-three",
        "CVE-2026-1111",
    }


def test_same_advisory_across_ecosystems_keeps_package_and_fix_details_scoped():
    first = finding(
        "OSV-one", ["CVE-2026-1000"], "one", "PyPI", details="Fixed in 2.0."
    )
    second = finding(
        "OSV-two", ["CVE-2026-1000"], "two", "npm", details="Fixed in 4.0."
    )
    [grouped] = group_security_findings([first, second])
    assert {
        (item["ecosystem"], item["dependency"], item["details"])
        for item in grouped["component_details"]
    } == {("PyPI", "one", "Fixed in 2.0."), ("npm", "two", "Fixed in 4.0.")}
    assert "Fixed in" not in grouped["details"]


def test_preserves_multiple_details_and_urls_for_same_component_and_advisory():
    first = finding("OSV-one", details="Fixed in 2.0.")
    second = finding(
        "OSV-one",
        details="Fixed in 1.2 on maintenance branch.",
        url="https://example.org/advisory",
    )
    [grouped] = group_security_findings([first, second])
    assert len(grouped["component_details"]) == 2
    assert set(grouped["references"]) == {first["url"], second["url"]}
    assert len(grouped["affected"]) == 1


def test_duplicate_records_and_affected_rows_do_not_duplicate_output():
    item = finding("OSV-one")
    item["affected"] *= 2
    [grouped] = group_security_findings([item, deepcopy(item)])
    assert len(grouped["affected"]) == 1
    assert len(grouped["component_details"]) == 1


def test_event_and_incoming_key_survive_when_primary_missing_from_advisory_ids():
    item = finding("OSV-old", ["CVE-2026-1000"])
    item["advisory_ids"] = ["CVE-2026-1000"]
    item["key"] = "existing-custom-marker"
    [grouped] = group_security_findings([item])
    assert "OSV-old" in grouped["advisory_ids"]
    assert "existing-custom-marker" in grouped["legacy_keys"]
    assert key("Go", "example.org/one", "OSV-old") in grouped["legacy_keys"]


def test_prior_grouped_markers_survive_later_alias_addition():
    [old] = group_security_findings([finding("OSV-one")])
    new = finding("CVE-2026-1000", ["OSV-one"])
    [grouped] = group_security_findings([old, new])
    assert old["key"] in grouped["legacy_keys"]
    assert set(old["legacy_keys"]) <= set(grouped["legacy_keys"])


def test_earlier_grouped_key_is_recognized_without_old_report_input():
    [grouped] = group_security_findings([finding("GO-one", ["CVE-2026-1000"])])
    assert key("advisory", "", "GO-one") in grouped["legacy_keys"]


def test_updates_are_unchanged_and_input_is_not_mutated():
    update = {**finding("2.0.0"), "kind": "update"}
    security = finding("OSV-one", ["CVE-2026-1000"])
    inputs = [update, security]
    snapshot = deepcopy(inputs)
    output = group_security_findings(inputs)
    assert next(item for item in output if item["kind"] == "update") == update
    assert inputs == snapshot


def test_empty_input():
    assert group_security_findings([]) == []
