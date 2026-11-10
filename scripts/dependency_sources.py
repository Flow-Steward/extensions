"""Bounded read clients for GitHub, public registries and OSV."""

from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache

from dependency_inventory import Dependency, Extension, source_file
from packaging.version import InvalidVersion, Version

GITHUB = "https://api.github.com"
MAX_FILE = 2 * 1024 * 1024
MAX_RESPONSE = 32 * 1024 * 1024
MAX_FILES = 150
HOSTS = {
    "api.github.com",
    "pypi.org",
    "registry.npmjs.org",
    "proxy.golang.org",
    "api.osv.dev",
    "go.dev",
}


class SourceError(Exception):
    """A check could not be completed; never interpreted as no findings."""


class NotFound(SourceError):
    """An optional public registry/source entry does not exist."""


class NoStableRelease(SourceError):
    """The source responded successfully but has no comparable stable releases."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SourceError(
            "source redirected; inspect the source mapping before following it"
        )


class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    """Release downloads carry no credentials, including across signed redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_release_url(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected:
            redirected.remove_header("Authorization")
        return redirected


def check_release_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname
        not in {
            "github.com",
            "release-assets.githubusercontent.com",
            "objects.githubusercontent.com",
        }
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
    ):
        raise SourceError("unsupported release asset URL")


class HTTP:
    def __init__(self, token=""):
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())
        self.last_mutation = None

    def download(self, url, *, max_bytes):
        check_release_url(url)
        request = urllib.request.Request(
            url, headers={"User-Agent": "flow-steward-dependency-monitor"}
        )
        try:
            with urllib.request.build_opener(ReleaseRedirect()).open(
                request, timeout=60
            ) as response:
                data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise SourceError("release asset exceeds its declared size")
            return data
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Signed redirect query strings are temporary credentials: never log them.
            raise SourceError(
                f"release asset download failed ({type(exc).__name__})"
            ) from None

    def text(self, url, *, method="GET", body=None):
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in HOSTS
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
        ):
            raise SourceError("unsupported source URL")
        headers = {
            "User-Agent": "flow-steward-dependency-monitor",
            "Accept": "application/json",
        }
        if parsed.hostname == "api.github.com":
            headers["X-GitHub-Api-Version"] = "2022-11-28"
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
        data = None if body is None else json.dumps(body).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        if parsed.hostname == "api.github.com" and method in {"POST", "PATCH"}:
            if self.last_mutation is not None:
                time.sleep(max(0, 1.1 - (time.monotonic() - self.last_mutation)))
            self.last_mutation = time.monotonic()
        for attempt in range(3):
            try:
                with self.opener.open(request, timeout=30) as response:
                    content = response.read(MAX_RESPONSE + 1)
                if len(content) > MAX_RESPONSE:
                    raise SourceError(f"response exceeds limit: {parsed.hostname}")
                return content.decode("utf-8")
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise NotFound(f"HTTP 404: {url}") from None
                # Never retry writes: the server may have accepted the first POST.
                if method == "GET" and exc.code in {429, 502, 503, 504} and attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise SourceError(f"HTTP {exc.code}: {url}") from None
            except (urllib.error.URLError, TimeoutError, UnicodeError, OSError) as exc:
                raise SourceError(
                    f"request failed ({type(exc).__name__}): {parsed.hostname}"
                ) from None
        raise SourceError("request attempts exhausted")

    def json(self, url, *, method="GET", body=None):
        try:
            return json.loads(self.text(url, method=method, body=body))
        except ValueError:
            raise SourceError(
                f"invalid JSON from {urllib.parse.urlsplit(url).hostname}"
            ) from None


def version_key(value: str) -> Version | None:
    try:
        return Version(value.removesuffix("+incompatible"))
    except InvalidVersion:
        return None


def stable_newer(current: str, latest: str) -> bool:
    old, new = version_key(current), version_key(latest)
    return bool(
        old is not None
        and new is not None
        and not new.is_prerelease
        and not new.is_devrelease
        and new > old
    )


def newest(values) -> str:
    stable = [
        (key, value)
        for value in values
        if (key := version_key(value)) is not None
        and not key.is_prerelease
        and not key.is_devrelease
    ]
    if not stable:
        return ""
    return max(stable)[1]


def quote(value):
    return urllib.parse.quote(value, safe="")


def validate_slug(slug):
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", slug):
        raise SourceError("invalid GitHub repository")
    return slug


class Services:
    def __init__(self, http):
        self.http = http
        self.source = lru_cache(maxsize=256)(self.source)
        self.upstream_go_mod = lru_cache(maxsize=128)(self.upstream_go_mod)
        self._latest = lru_cache(maxsize=4096)(self._latest)
        self._vulnerabilities = lru_cache(maxsize=8192)(self._vulnerabilities)
        self._runtime_asset = lru_cache(maxsize=256)(self._runtime_asset)

    def _runtime_asset(self, coordinates):
        from runtime_inventory import RuntimeAsset, inspect_runtime_archive

        asset = RuntimeAsset(*coordinates)
        data = self.http.download(asset.url, max_bytes=asset.size)
        return inspect_runtime_archive(data, asset)

    def runtime_inventory(self, ext):
        from dependency_inventory import Inventory

        result = Inventory()
        if not ext.assets:
            result.gaps.append(
                "Published runtime assets are unavailable; binary composition cannot be checked"
            )
        for coordinates in ext.assets:
            inventory = self._runtime_asset(coordinates)
            result.dependencies.extend(inventory.dependencies)
            result.gaps.extend(inventory.gaps)
        return result

    def pages(self, path):
        result = []
        for page in range(1, 101):
            sep = "&" if "?" in path else "?"
            values = self.http.json(f"{GITHUB}{path}{sep}per_page=100&page={page}")
            if not isinstance(values, list):
                raise SourceError("GitHub list response is malformed")
            result.extend(values)
            if len(values) < 100:
                return result
        raise SourceError("GitHub pagination limit reached; inventory is incomplete")

    def source(self, ext: Extension):
        base = f"{GITHUB}/repos/{validate_slug(ext.repository)}"
        commit = self.http.json(f"{base}/commits/{quote(ext.tag)}")
        sha = commit["sha"]
        tree_sha = commit["commit"]["tree"]["sha"]
        if not all(re.fullmatch(r"[a-f0-9]{40}", value) for value in (sha, tree_sha)):
            raise SourceError("invalid source commit/tree")
        tree = self.http.json(f"{base}/git/trees/{tree_sha}?recursive=1")
        if tree.get("truncated"):
            raise SourceError(f"truncated source tree: {ext.repository}")
        paths, files = [], {}
        for entry in tree["tree"]:
            path = entry["path"]
            if entry["type"] != "blob":
                continue
            paths.append(path)
            if not source_file(path):
                continue
            if entry["mode"] == "120000":
                raise SourceError(f"dependency file is a symlink: {path}")
            if entry.get("size", MAX_FILE + 1) > MAX_FILE or len(files) >= MAX_FILES:
                raise SourceError(f"dependency inventory limit exceeded: {path}")
            blob = self.http.json(f"{base}/git/blobs/{entry['sha']}")
            files[path] = self.decode_file(blob)
        return sha, files, paths

    @staticmethod
    def decode_file(blob):
        if blob.get("encoding") != "base64":
            raise SourceError("dependency file encoding is unsupported")
        try:
            data = base64.b64decode(blob["content"], validate=False)
            if len(data) > MAX_FILE:
                raise SourceError("dependency file exceeds size limit")
            return data.decode("utf-8")
        except (ValueError, UnicodeError):
            raise SourceError("invalid dependency file encoding") from None

    def upstream_go_mod(self, repository, commit):
        validate_slug(repository)
        if not re.fullmatch(r"[a-fA-F0-9]{40}", commit):
            raise SourceError("upstream Go source requires a pinned commit")
        try:
            blob = self.http.json(
                f"{GITHUB}/repos/{repository}/contents/go.mod?ref={commit}"
            )
        except NotFound:
            return None
        return self.decode_file(blob)

    def latest(self, dep: Dependency):
        latest = self._latest(dep.ecosystem, dep.name)
        if not latest:
            raise NoStableRelease(
                "no comparable stable releases returned by the registry"
            )
        return latest

    def _latest(self, ecosystem, name):
        if ecosystem == "PyPI":
            data = self.http.json(f"https://pypi.org/pypi/{quote(name)}/json")
            return newest(
                v
                for v, files in data["releases"].items()
                if any(not f.get("yanked", False) for f in files)
            )
        if ecosystem == "npm":
            data = self.http.json(f"https://registry.npmjs.org/{quote(name)}/latest")
            return data["version"]
        if ecosystem == "Go":
            if name in {"stdlib", "toolchain"}:
                data = self.http.json("https://go.dev/dl/?mode=json")
                return newest(
                    r["version"].removeprefix("go") for r in data if r.get("stable")
                )
            # Go's module proxy escapes uppercase characters with !lowercase.
            escaped = "".join("!" + c.lower() if c.isupper() else c for c in name)
            data = self.http.text(
                f"https://proxy.golang.org/{urllib.parse.quote(escaped, safe='/!')}/@v/list"
            )
            return newest(data.splitlines())
        if ecosystem == "GitHub":
            releases = self.pages(f"/repos/{validate_slug(name)}/releases")
            return newest(
                r["tag_name"]
                for r in releases
                if not r.get("draft") and not r.get("prerelease")
            )
        raise SourceError(f"unsupported update ecosystem: {ecosystem}")

    def vulnerabilities(self, dep: Dependency):
        return self._vulnerabilities(dep.ecosystem, dep.name, dep.version, dep.commit)

    def _vulnerabilities(self, ecosystem, name, version, commit):
        if ecosystem == "GitHub":
            query = (
                {"commit": commit}
                if commit
                else {
                    "package": {
                        "ecosystem": "GIT",
                        "name": f"https://github.com/{name}",
                    },
                    "version": version,
                }
            )
        else:
            query = {
                "package": {"ecosystem": ecosystem, "name": name},
                "version": version,
            }
        result, seen = [], set()
        for _ in range(100):
            data = self.http.json(
                "https://api.osv.dev/v1/query", method="POST", body=query
            )
            result.extend(v for v in data.get("vulns", []) if not v.get("withdrawn"))
            token = data.get("next_page_token")
            if not token:
                return result
            if token in seen:
                raise SourceError("OSV repeated a pagination token")
            seen.add(token)
            query = {**query, "page_token": token}
        raise SourceError("OSV pagination limit reached")

    def list_issues(self, repository):
        return [
            i
            for i in self.pages(f"/repos/{validate_slug(repository)}/issues?state=all")
            if "pull_request" not in i
        ]

    def create_issue(self, repository, title, body):
        return self.http.json(
            f"{GITHUB}/repos/{validate_slug(repository)}/issues",
            method="POST",
            body={"title": title, "body": body},
        )

    def update_issue(self, repository, number, body):
        return self.http.json(
            f"{GITHUB}/repos/{validate_slug(repository)}/issues/{int(number)}",
            method="PATCH",
            body={"body": body},
        )
