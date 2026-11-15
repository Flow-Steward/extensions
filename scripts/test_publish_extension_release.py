"""Offline publishing boundary tests: fake gh is the only GitHub interface."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).parent
SCRIPT = HERE / "publish_extension_release.py"
REPOSITORY = "Flow-Steward/ext-fixture"
TAG = "v0.1.1"
SHA = "a" * 40


@pytest.fixture
def publishing(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    filename = "flowsteward.fixture-0.1.1.zip"
    manifest = {
        "manifest_version": 2,
        "extension_id": "flowsteward.fixture",
        "version": "0.1.1",
        "kind": "tool_provider",
        "display_name": "Fixture",
        "description": "A representative extension for offline release publication boundary testing.",
        "listing": {"category": "data", "summary": "A release publication fixture."},
        "features": ["tool"],
        "required_scopes": ["extension:invoke"],
        "runtime": {"contract_version": "extension_host_v2"},
    }
    with zipfile.ZipFile(artifacts / filename, "w") as archive:
        archive.writestr("flowsteward_fixture/extension.yaml", yaml.safe_dump(manifest))
        archive.writestr("flowsteward_fixture/main.py", "print('fixture')\n")
        archive.writestr(
            "flowsteward_fixture/icon.png",
            b"\x89PNG\r\n\x1a\n"
            + struct.pack(">I", 13)
            + b"IHDR"
            + struct.pack(">II", 128, 128),
        )
    data = (artifacts / filename).read_bytes()
    plan = {
        "schema_version": 1,
        "repository": REPOSITORY,
        "tag": TAG,
        "source_sha": SHA,
        "extension_id": "flowsteward.fixture",
        "runtime_targets": [""],
        "assets": [
            {
                "filename": filename,
                "target": "",
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "kind": "extension",
            }
        ],
    }
    plan_path = artifacts / "release-plan.json"
    state_path = tmp_path / "state.json"
    binary = tmp_path / "bin" / "gh"
    binary.parent.mkdir()
    binary.write_text(
        f"#!{sys.executable}\nSTATE_PATH = {str(state_path)!r}\n"
        + """
import json,os,sys
from pathlib import Path
state_path=Path(STATE_PATH)
s=json.loads(state_path.read_text());args=sys.argv[1:];s["calls"].append(args)
s["auth_context"]={"host":os.environ.get("GH_HOST"),"config":os.environ.get("GH_CONFIG_DIR"),"home":os.environ.get("HOME"),"debug":bool(os.environ.get("GH_DEBUG")),"fallback":bool(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_ENTERPRISE_TOKEN")),"explicit_token":bool(os.environ.get("GH_TOKEN"))}
state_path.write_text(json.dumps(s))
def response(status,body):
 print("HTTP/2.0 "+str(status)+" Fake\\nContent-Type: application/json\\n\\n"+json.dumps(body))
 sys.exit(0 if status==200 else 1)
if args[:2]==["release","create"]:
 if s.get("create_failure"):sys.exit(1)
 s["exists"]=True;s["create_args"]=args
 if "visibility_after_create" in s:s["private_repo"]=s["visibility_after_create"]
 state_path.write_text(json.dumps(s));print("https://github.com/"+s["repository"]+"/releases/tag/"+s["tag"]);sys.exit(0)
if args[:1]!=["api"]:sys.exit(99)
endpoint=args[-1]
if endpoint=="repos/"+s["repository"]:response(200,{"full_name":s["repository"],"private":s.get("private_repo",False),"visibility":s.get("visibility","private" if s.get("private_repo",False) is True else "public")})
if "/git/ref/tags/" in endpoint:
 response(200,{"object":{"type":"tag" if s.get("annotated") else "commit","sha":"b"*40 if s.get("annotated") else s["tag_sha"]}})
if "/git/tags/" in endpoint:response(200,{"object":{"type":"commit","sha":s["tag_sha"]}})
if "/releases/10/assets?per_page=100" in endpoint:response(200,s["assets"])
if "/releases/tags/" in endpoint:
 if s.get("api_status"):response(s["api_status"],{"message":"failure"})
 if not s["exists"]:response(404,{"message":"Not Found"})
 response(200,{"id":10,"tag_name":s["tag"],"draft":s.get("draft",False),"prerelease":s.get("prerelease",False),"assets":s["assets"]})
if "/releases/assets/" in endpoint:
 if s.get("download_error"):sys.exit(1)
 if s.get("private_repo") and (not os.environ.get("GH_TOKEN") or "Accept: application/octet-stream" not in args):sys.exit(97)
 asset_id=int(endpoint.rsplit("/",1)[-1]);asset=next(a for a in s["assets"] if a["id"]==asset_id)
 data=Path(s["artifact_dir"],asset["name"]).read_bytes()
 if s.get("bad_download"):data=b"x"*len(data)
 sys.stdout.buffer.write(data);sys.exit(0)
sys.exit(98)
"""
    )
    binary.chmod(0o700)
    state = {
        "repository": REPOSITORY,
        "tag": TAG,
        "tag_sha": SHA,
        "exists": False,
        "calls": [],
        "artifact_dir": str(artifacts),
        "assets": [{"id": 20, "name": filename, "size": len(data)}],
    }

    def save():
        plan_path.write_text(json.dumps(plan))
        state_path.write_text(json.dumps(state))

    def run(*extra, **environment):
        save()
        env = {
            **os.environ,
            "PATH": str(binary.parent) + os.pathsep + os.environ["PATH"],
            "GH_TOKEN": "offline-test-token",
            "GITHUB_ACTIONS": "true",
            "RUNNER_ENVIRONMENT": "github-hosted",
            **environment,
        }
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--artifact-dir",
                str(artifacts),
                "--repository",
                REPOSITORY,
                "--tag",
                TAG,
                "--source-sha",
                SHA,
                *extra,
            ],
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        state.update(json.loads(state_path.read_text()))
        return result

    return artifacts, plan, state, run


def test_create_uses_verified_tag_exact_target_and_generated_notes(publishing):
    artifacts, plan, state, run = publishing
    result = run()
    assert result.returncode == 0, result.stderr
    create = state["create_args"]
    assert create[:3] == ["release", "create", TAG]
    assert create[create.index("--target") + 1] == SHA
    assert "--verify-tag" in create and "--generate-notes" in create
    assert str(artifacts / plan["assets"][0]["filename"]) in create
    assert sum(c[:2] == ["release", "create"] for c in state["calls"]) == 1


@pytest.mark.parametrize(
    "change",
    [
        "repository",
        "tag",
        "source_sha",
        "hash",
        "size",
        "traversal",
        "symlink",
        "extra",
        "notes",
    ],
)
def test_invalid_local_plan_is_rejected_before_any_github_call(publishing, change):
    artifacts, plan, state, run = publishing
    if change in ("repository", "tag", "source_sha"):
        plan[change] = {
            "repository": "Flow-Steward/ext-other",
            "tag": "v9.9.9",
            "source_sha": "b" * 40,
        }[change]
    elif change == "hash":
        plan["assets"][0]["sha256"] = "0" * 64
    elif change == "size":
        plan["assets"][0]["bytes"] += 1
    elif change == "traversal":
        plan["assets"][0]["filename"] = "../escape.zip"
    elif change == "symlink":
        path = artifacts / plan["assets"][0]["filename"]
        data = path.read_bytes()
        path.unlink()
        outside = artifacts.parent / "outside.zip"
        outside.write_bytes(data)
        path.symlink_to(outside)
    elif change == "extra":
        (artifacts / "unexpected").write_text("extra")
    else:
        plan["notes_file"] = "absent.md"
    result = run()
    assert result.returncode != 0
    assert state["calls"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("tag_sha", "b" * 40),
        ("draft", True),
        ("prerelease", True),
        ("bad_download", True),
    ],
)
def test_existing_release_mismatch_never_mutates(publishing, field, value):
    _, _, state, run = publishing
    state.update(exists=True, **{field: value})
    result = run()
    assert result.returncode != 0
    assert not any(c[:2] == ["release", "create"] for c in state["calls"])


def test_identical_existing_annotated_release_downloads_and_verifies_assets(publishing):
    _, _, state, run = publishing
    state.update(exists=True, annotated=True)
    result = run()
    assert result.returncode == 0, result.stderr
    assert not any(c[:2] == ["release", "create"] for c in state["calls"])
    assert any("/releases/assets/" in c[-1] for c in state["calls"])


@pytest.mark.parametrize("change", ["missing", "extra", "size", "duplicate"])
def test_existing_release_requires_the_exact_asset_set(publishing, change):
    _, _, state, run = publishing
    state["exists"] = True
    if change == "missing":
        state["assets"] = []
    elif change == "extra":
        state["assets"].append({"id": 21, "name": "extra.txt", "size": 1})
    elif change == "size":
        state["assets"][0]["size"] += 1
    else:
        state["assets"].append(dict(state["assets"][0]))
    result = run()
    assert result.returncode != 0
    assert not any(c[:2] == ["release", "create"] for c in state["calls"])


def test_github_lookup_failure_is_not_treated_as_absent_release(publishing):
    _, _, state, run = publishing
    state["api_status"] = 403
    assert run().returncode != 0
    assert not any(c[:2] == ["release", "create"] for c in state["calls"])


@pytest.mark.parametrize(
    "environment",
    [
        {"GH_TOKEN": ""},
        {"GITHUB_ACTIONS": "false"},
        {"RUNNER_ENVIRONMENT": "self-hosted"},
    ],
)
def test_requires_explicit_hosted_runner_token(publishing, environment):
    _, _, state, run = publishing
    assert run(**environment).returncode != 0
    assert state["calls"] == []


def test_custom_notes_are_a_verified_additional_asset(publishing):
    artifacts, plan, state, run = publishing
    notes = b"Release-specific operator notes.\n"
    (artifacts / "RELEASE_NOTES.md").write_bytes(notes)
    plan["assets"].append(
        {
            "filename": "RELEASE_NOTES.md",
            "target": "",
            "bytes": len(notes),
            "sha256": hashlib.sha256(notes).hexdigest(),
            "kind": "additional",
        }
    )
    plan["notes_file"] = "RELEASE_NOTES.md"
    state["assets"].append({"id": 21, "name": "RELEASE_NOTES.md", "size": len(notes)})
    result = run()
    assert result.returncode == 0, result.stderr
    create = state["create_args"]
    assert create[create.index("--notes-file") + 1] == str(
        artifacts / "RELEASE_NOTES.md"
    )
    assert "--generate-notes" not in create


def test_private_repository_is_refused_without_release_creation(publishing):
    _, _, state, run = publishing
    state["private_repo"] = True
    result = run()
    assert result.returncode != 0
    assert not any(c[:2] == ["release", "create"] for c in state["calls"])


def test_creation_failure_is_not_retried_or_repaired(publishing):
    _, _, state, run = publishing
    state["create_failure"] = True
    assert run().returncode != 0
    assert sum(c[:2] == ["release", "create"] for c in state["calls"]) == 1
    assert all(c[0] == "api" or c[:2] == ["release", "create"] for c in state["calls"])


@pytest.mark.parametrize(
    "argument,value",
    [
        ("--repository", "other/ext-fixture"),
        ("--tag", "v0.1.1;touch injected"),
        ("--source-sha", "abc"),
    ],
)
def test_untrusted_cli_identity_is_rejected_before_github(publishing, argument, value):
    _, _, state, run = publishing
    assert run(argument, value).returncode != 0
    assert state["calls"] == []


def test_gh_uses_isolated_configuration_and_only_explicit_job_token(publishing):
    artifacts, _, state, run = publishing
    result = run(
        GH_HOST="evil.invalid",
        GH_CONFIG_DIR=str(artifacts),
        GH_DEBUG="api",
        GITHUB_TOKEN="ignored-fallback",
        GH_ENTERPRISE_TOKEN="ignored-enterprise",
    )
    assert result.returncode == 0, result.stderr
    context = state["auth_context"]
    assert context["host"] == "github.com"
    assert context["config"] == context["home"]
    assert context["config"] != str(artifacts)
    assert context["explicit_token"] is True
    assert context["debug"] is False and context["fallback"] is False


@pytest.mark.parametrize("exists", [False, True])
def test_explicit_private_mode_creates_or_verifies_authenticated_release(
    publishing, exists
):
    _, _, state, run = publishing
    state.update(private_repo=True, exists=exists, annotated=exists)
    result = run("--expected-visibility", "private")
    assert result.returncode == 0, result.stderr
    assert sum(c[:2] == ["release", "create"] for c in state["calls"]) == (
        0 if exists else 1
    )
    assert any("/releases/assets/" in c[-1] for c in state["calls"])
    assert state["auth_context"]["explicit_token"] is True
    assert all(c[0] == "api" or c[:2] == ["release", "create"] for c in state["calls"])


@pytest.mark.parametrize(
    "actual,visibility",
    [
        (False, "public"),
        (None, "private"),
        (0, "private"),
        ("false", "private"),
        (True, "public"),
        (True, "internal"),
        (True, None),
    ],
)
def test_explicit_private_mode_refuses_non_private_metadata_before_release_access(
    publishing, actual, visibility
):
    _, _, state, run = publishing
    state.update(private_repo=actual, visibility=visibility)
    result = run("--expected-visibility", "private")
    assert result.returncode != 0
    assert "visibility" in result.stderr
    assert state["calls"]
    assert not any("/git/" in c[-1] or "/releases/" in c[-1] for c in state["calls"])
    assert all(c[0] == "api" for c in state["calls"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("tag_sha", "b" * 40),
        ("draft", True),
        ("prerelease", True),
        ("bad_download", True),
        ("download_error", True),
        ("api_status", 403),
    ],
)
def test_private_release_readback_failure_never_mutates(publishing, field, value):
    _, _, state, run = publishing
    state.update(private_repo=True, exists=True, **{field: value})
    result = run("--expected-visibility", "private")
    assert result.returncode != 0
    assert state["calls"]
    assert not any(c[:2] == ["release", "create"] for c in state["calls"])


def test_private_mode_revalidates_archive_hash_before_github(publishing):
    _, plan, state, run = publishing
    state["private_repo"] = True
    plan["assets"][0]["sha256"] = "0" * 64
    result = run("--expected-visibility", "private")
    assert result.returncode != 0
    assert "SHA256" in result.stderr
    assert state["calls"] == []


def test_private_mode_detects_visibility_change_during_creation_without_repair(
    publishing,
):
    _, _, state, run = publishing
    state.update(private_repo=True, visibility_after_create=False)
    result = run("--expected-visibility", "private")
    assert result.returncode != 0
    assert "visibility" in result.stderr
    assert sum(c[:2] == ["release", "create"] for c in state["calls"]) == 1
    assert all(c[0] == "api" or c[:2] == ["release", "create"] for c in state["calls"])


def test_prepare_build_verify_plan_and_private_publication_share_one_identity(
    publishing, tmp_path
):
    from test_release_extension import commit

    artifacts, plan, state, run = publishing
    root = tmp_path / "source"
    root.mkdir()
    with zipfile.ZipFile(artifacts / plan["assets"][0]["filename"]) as archive:
        for name in archive.namelist():
            relative = name.removeprefix("flowsteward_fixture/")
            assert relative != name
            (root / relative).write_bytes(archive.read(name))
    (root / ".github").mkdir()
    (root / ".github/release-config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "extension_id": "flowsteward.fixture",
                "runtime_targets": [""],
                "test_requirements": [],
                "test_paths": [],
                "additional_assets": [],
            }
        )
    )
    source_sha = commit(root)
    for path in artifacts.iterdir():
        path.unlink()
    base = [sys.executable, str(HERE / "release_extension.py")]
    identity = ["--repository", REPOSITORY, "--tag", TAG]
    source = [
        "--source-root",
        str(root),
        *identity,
        "--config",
        ".github/release-config.json",
    ]
    commands = [
        [*base, "prepare", *source],
        [
            *base,
            "build",
            *source,
            "--out-dir",
            str(artifacts),
            "--catalog-root",
            str(HERE.parent),
        ],
        [
            *base,
            "verify-plan",
            *identity,
            "--source-sha",
            source_sha,
            "--artifact-dir",
            str(artifacts),
            "--catalog-root",
            str(HERE.parent),
        ],
    ]
    for command in commands:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    plan.clear()
    plan.update(json.loads((artifacts / "release-plan.json").read_text()))
    assert plan["source_sha"] == source_sha
    state.update(private_repo=True, tag_sha=source_sha)
    state["assets"][0]["size"] = plan["assets"][0]["bytes"]
    result = run("--expected-visibility", "private", "--source-sha", source_sha)
    assert result.returncode == 0, result.stderr
    assert (
        state["create_args"][state["create_args"].index("--target") + 1] == source_sha
    )
    assert any("/releases/assets/" in c[-1] for c in state["calls"])
