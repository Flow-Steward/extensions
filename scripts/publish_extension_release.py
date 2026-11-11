"""Publish a verified extension artifact on a GitHub-hosted runner only.

The trusted catalog verifier owns archive inspection. This helper repeats that
verification, uses only the job's explicit token, and never repairs an existing
release: an identical public release is verified; every mismatch fails closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import release_extension


class PublishError(Exception):
    """Publication cannot safely continue."""


def _require(condition, message):
    if not condition:
        raise PublishError(message)


class GitHub:
    """A noninteractive gh process with isolated configuration and explicit auth."""

    def __init__(self, directory):
        token = os.environ.get("GH_TOKEN", "")
        _require(bool(token), "a job-local GH_TOKEN is required")
        _require(
            os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted",
            "publication requires a GitHub-hosted Actions runner",
        )
        self.command = shutil.which("gh")
        _require(self.command is not None, "GitHub CLI is required")
        self.directory = str(directory)
        self.environment = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": self.directory,
            "XDG_CONFIG_HOME": self.directory,
            "GH_CONFIG_DIR": self.directory,
            "GH_TOKEN": token,
            "GH_HOST": "github.com",
            "GH_PROMPT_DISABLED": "1",
            "GH_PAGER": "cat",
            "NO_COLOR": "1",
        }

    def run(self, args):
        try:
            return subprocess.run(
                [self.command, *args],
                env=self.environment,
                cwd=self.directory,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=180,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PublishError(
                "GitHub CLI request failed; publication was not retried"
            ) from exc

    def api(self, endpoint, *, allow_missing=False):
        result = self.run(
            [
                "api",
                "--hostname",
                "github.com",
                "--method",
                "GET",
                "--include",
                endpoint,
            ]
        )
        parts = re.split(rb"\r?\n\r?\n", result.stdout, maxsplit=1)
        _require(len(parts) == 2, "GitHub returned no verifiable HTTP response")
        header, body = parts
        match = re.match(rb"HTTP/\S+\s+(\d{3})(?:\s|$)", header)
        _require(match is not None, "GitHub returned an invalid HTTP status")
        status = int(match[1])
        if allow_missing and status == 404:
            return None
        _require(
            status == 200 and result.returncode == 0,
            "GitHub read failed; an error is not an absent release",
        )
        try:
            return json.loads(body)
        except (ValueError, UnicodeError) as exc:
            raise PublishError("GitHub returned invalid JSON") from exc

    def download(self, repository, asset_id):
        result = self.run(
            [
                "api",
                "--hostname",
                "github.com",
                "--method",
                "GET",
                "-H",
                "Accept: application/octet-stream",
                f"repos/{repository}/releases/assets/{asset_id}",
            ]
        )
        _require(result.returncode == 0, "release asset download failed")
        return result.stdout


def _tag_commit(github, repository, tag):
    reference = github.api(f"repos/{repository}/git/ref/tags/{tag}")
    for _ in range(8):
        obj = reference.get("object", {}) if isinstance(reference, dict) else {}
        sha, kind = obj.get("sha"), obj.get("type")
        _require(
            isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha),
            "tag has no valid commit identity",
        )
        if kind == "commit":
            return sha
        _require(kind == "tag", "tag does not resolve to a commit")
        reference = github.api(f"repos/{repository}/git/tags/{sha}")
    raise PublishError("annotated tag chain is too deep")


def _verify_release(github, repository, tag, source_sha, plan, release):
    _require(
        isinstance(release, dict)
        and release.get("tag_name") == tag
        and release.get("draft") is False
        and release.get("prerelease") is False,
        "existing release must be public, non-draft and non-prerelease",
    )
    _require(
        _tag_commit(github, repository, tag) == source_sha,
        "release tag commit does not match expected source SHA",
    )
    release_id = release.get("id")
    _require(
        type(release_id) is int and release_id > 0, "release has no valid numeric ID"
    )
    # The plan is limited to 30 assets. A page of 100 cannot hide extra assets:
    # any full page already exceeds the exact expected set and is rejected.
    assets = github.api(f"repos/{repository}/releases/{release_id}/assets?per_page=100")
    _require(
        isinstance(assets, list) and len(assets) == len(plan["assets"]),
        "release asset count differs from verified plan",
    )
    expected = {row["filename"]: row for row in plan["assets"]}
    seen = set()
    for asset in assets:
        _require(isinstance(asset, dict), "invalid remote asset metadata")
        name, asset_id = asset.get("name"), asset.get("id")
        _require(
            isinstance(name, str) and name in expected and name not in seen,
            "release assets differ from verified plan",
        )
        seen.add(name)
        row = expected[name]
        _require(
            type(asset_id) is int
            and asset_id > 0
            and type(asset.get("size")) is int
            and asset["size"] == row["bytes"],
            "release asset identity or size differs from verified plan",
        )
        data = github.download(repository, asset_id)
        _require(
            len(data) == row["bytes"]
            and hashlib.sha256(data).hexdigest() == row["sha256"],
            "downloaded release asset SHA256 or size differs from verified plan",
        )
    _require(seen == set(expected), "release is missing verified assets")


def publish(artifact_dir, repository, tag, source_sha):
    _require(
        isinstance(repository, str)
        and re.fullmatch(r"Flow-Steward/ext-[a-z0-9]+(?:-[a-z0-9]+)*", repository),
        "expected a Flow-Steward/ext-* repository",
    )
    _require(
        isinstance(tag, str) and re.fullmatch(r"v\d+\.\d+\.\d+", tag),
        "expected a stable vMAJOR.MINOR.PATCH tag",
    )
    _require(
        isinstance(source_sha, str) and re.fullmatch(r"[0-9a-f]{40}", source_sha),
        "expected a full source commit SHA",
    )
    root = Path(artifact_dir).resolve()
    with tempfile.TemporaryDirectory(prefix="extension-publish-gh-") as isolated:
        github = GitHub(isolated)
        plan = release_extension.verify_plan(
            root, repository, tag, source_sha, Path(__file__).resolve().parents[1]
        )
        for row in plan["assets"]:
            _require(
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", row["filename"]),
                "release asset basename contains GitHub CLI metacharacters",
            )
        notes_file = plan.get("notes_file")
        if notes_file is not None:
            _require(
                any(
                    row["filename"] == notes_file and row["kind"] == "additional"
                    for row in plan["assets"]
                ),
                "notes_file must identify a verified additional asset",
            )
        metadata = github.api(f"repos/{repository}")
        _require(
            isinstance(metadata, dict)
            and metadata.get("full_name") == repository
            and metadata.get("private") is False,
            "publication requires the expected public repository",
        )
        _require(
            _tag_commit(github, repository, tag) == source_sha,
            "remote tag commit does not match expected source SHA",
        )
        endpoint = f"repos/{repository}/releases/tags/{tag}"
        release = github.api(endpoint, allow_missing=True)
        created = release is None
        if created:
            args = [
                "release",
                "create",
                tag,
                "--repo",
                repository,
                "--verify-tag",
                "--target",
                source_sha,
                "--draft=false",
                "--prerelease=false",
            ]
            args += (
                ["--notes-file", str(root / notes_file)]
                if notes_file
                else ["--generate-notes"]
            )
            args += [str(root / row["filename"]) for row in plan["assets"]]
            result = github.run(args)
            _require(
                result.returncode == 0,
                "release creation failed or its outcome is unknown; no repair or retry was attempted",
            )
            release = github.api(endpoint)
        _verify_release(github, repository, tag, source_sha, plan, release)
    return {
        "repository": repository,
        "tag": tag,
        "source_sha": source_sha,
        "created": created,
        "verified_assets": len(plan["assets"]),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for argument in ("artifact-dir", "repository", "tag", "source-sha"):
        parser.add_argument("--" + argument, required=True)
    args = parser.parse_args(argv)
    try:
        result = publish(args.artifact_dir, args.repository, args.tag, args.source_sha)
    except (
        PublishError,
        release_extension.ReleaseError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
    ) as exc:
        parser.exit(2, f"Release publication refused: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
