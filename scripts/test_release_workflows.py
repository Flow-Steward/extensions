"""Publication must be isolated from extension-controlled build/test execution."""

import re
import shlex
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return yaml.load(
        (ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader
    )


def test_source_build_is_read_only_without_cache_access_or_persisted_credentials():
    flow = load("build-extension.yml")
    assert flow["permissions"] == {"contents": "read"}
    assert flow["cache-mode"] == "none"
    job = flow["jobs"]["build"]
    assert job["permissions"] == {"contents": "read"}
    for step in job["steps"]:
        assert "GH_TOKEN" not in step.get("env", {})
        if step.get("uses", "").startswith("actions/checkout@"):
            assert step["with"]["persist-credentials"] == "false"


def test_publisher_checks_out_only_immutable_trusted_tooling_and_uses_same_run_artifact():
    flow = load("release-extension.yml")
    assert set(flow["on"]) == {"workflow_call"}
    assert flow["cache-mode"] == "none"
    assert "workflow_dispatch" in flow["jobs"]["build"]["if"]
    assert "github.event_name == 'push'" in flow["jobs"]["build"]["if"]
    assert "pull_request" not in flow["jobs"]["build"]["if"]
    job = flow["jobs"]["publish"]
    assert job["needs"] == "build"
    assert job["permissions"] == {"contents": "write"}
    steps = job["steps"]
    checkouts = [s for s in steps if s.get("uses", "").startswith("actions/checkout@")]
    assert len(checkouts) == 1
    assert checkouts[0]["with"]["repository"] == "Flow-Steward/extensions"
    assert re.fullmatch("[0-9a-f]{40}", checkouts[0]["with"]["ref"])
    artifact = next(
        s for s in steps if s.get("uses", "").startswith("actions/download-artifact@")
    )
    assert "run-id" not in artifact["with"] and "github-token" not in artifact["with"]
    assert artifact["with"]["name"] == "${{ needs.build.outputs.artifact_name }}"
    runs = [s for s in steps if "run" in s]
    verify_index = next(i for i, s in enumerate(runs) if "verify-plan" in s["run"])
    publish_index = next(
        i for i, s in enumerate(runs) if "publish_extension_release.py" in s["run"]
    )
    assert verify_index < publish_index
    assert runs[publish_index]["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert sum("GH_TOKEN" in s.get("env", {}) for s in steps) == 1
    assert all("source/" not in s.get("run", "") for s in steps)


def test_external_actions_are_pinned_and_untrusted_expressions_are_not_interpolated_into_shell():
    for name in ["build-extension.yml", "release-extension.yml"]:
        flow = load(name)
        for job in flow["jobs"].values():
            for step in job.get("steps", []):
                if "uses" in step:
                    assert (
                        re.fullmatch(r"actions/[a-z-]+@[0-9a-f]{40}", step["uses"])
                        or step["uses"] == "docker/setup-qemu-action@99012661954931238ded8c8b007157a8430204e1"
                    )
                assert "${{" not in step.get("run", "")


def test_native_build_requires_explicit_opt_in_for_validation_and_publication():
    for name in ["build-extension.yml", "release-extension.yml"]:
        inputs = load(name)["on"]["workflow_call"]["inputs"]
        assert inputs.get("build_native", {}).get("type") == "boolean"
        assert inputs["build_native"]["default"] == "false"
        assert inputs["build_native"].get("required", "false") == "false"
    release = load("release-extension.yml")
    assert release["jobs"]["build"]["with"]["build_native"] == "${{ inputs.build_native }}"


def test_native_payloads_are_built_after_identity_and_before_recipe_preparation():
    job = load("build-extension.yml")["jobs"]["build"]
    steps = job["steps"]
    native = [step for step in steps if step.get("id", "").startswith("native_")]
    assert len(native) == 2
    assert all(step.get("if") == "${{ inputs.build_native }}" for step in native)
    identity = next(i for i, step in enumerate(steps) if step.get("id") == "identity")
    prepare = next(i for i, step in enumerate(steps) if "release_extension.py prepare" in step.get("run", ""))
    pull, build = native
    assert identity < steps.index(pull) < steps.index(build) < prepare
    assert shlex.split(pull["run"]) == [
        "docker", "pull",
        "golang:1.27.3-bookworm@sha256:dc0963f32053e4bc451d24d87e3892d42d01021b61f093e98eb95c0352bb84b0",
    ]
    assert build["working-directory"] == "source"
    assert shlex.split(build["run"]) == ["bash", "scripts/build_toolbox.sh"]
    assert job["timeout-minutes"] == "${{ inputs.build_native && 90 || 30 }}"


def test_native_build_keeps_source_execution_out_of_the_publisher():
    publish = load("release-extension.yml")["jobs"]["publish"]
    assert all(
        not step.get("id", "").startswith("native_")
        and "build_toolbox" not in step.get("run", "")
        for step in publish["steps"]
    )
    native = [
        step for step in load("build-extension.yml")["jobs"]["build"]["steps"]
        if step.get("id", "").startswith("native_")
    ]
    assert native
    for step in native:
        assert "env" not in step
        assert "docker.sock" not in step["run"]
        assert "--privileged" not in step["run"]
