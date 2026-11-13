"""Static discovery must retain real pins and expose gaps rather than invent them."""

import json

import pytest
from dependency_inventory import discover, select_extensions, source_file


def pins(inventory):
    return {(d.ecosystem, d.name, d.version) for d in inventory.dependencies}


def test_selects_published_registered_owner_not_id_prefix(tmp_path):
    entries = tmp_path / "extensions"
    entries.mkdir()
    for key, repo in [
        ("com.image.processing", "Flow-Steward/ext-image"),
        ("flowsteward.fake", "Flow-Steward-evil/ext-fake"),
        ("flowsteward.old", "Flow-Steward/ext-old"),
    ]:
        (entries / f"{key}.yaml").write_text(f"repository: https://github.com/{repo}\n")
    items = [
        {
            "extension_id": "com.image.processing",
            "version": "1.2.0",
            "publication_status": "published",
            "repository_url": "https://github.com/Flow-Steward/ext-image/tree/v1.2.0",
        },
        {
            "extension_id": "flowsteward.fake",
            "version": "1.0.0",
            "publication_status": "published",
            "repository_url": "https://github.com/Flow-Steward-evil/ext-fake/tree/v1.0.0",
        },
        {
            "extension_id": "flowsteward.old",
            "version": "1.0.0",
            "publication_status": "deprecated",
            "repository_url": "https://github.com/Flow-Steward/ext-old/tree/v1.0.0",
        },
    ]
    (tmp_path / "index.json").write_text(json.dumps({"items": items}))
    result = select_extensions(tmp_path)
    assert [(x.extension_id, x.repository, x.tag) for x in result] == [
        ("com.image.processing", "Flow-Steward/ext-image", "v1.2.0")
    ]
    items[0]["repository_url"] = "https://github.com/elsewhere/ext-image/tree/v1.2.0"
    (tmp_path / "index.json").write_text(json.dumps({"items": items}))
    with pytest.raises(ValueError, match="source"):
        select_extensions(tmp_path)


def test_manifest_and_architecture_wheels_preserve_evidence_and_scope():
    files = {
        "extension.yaml": "python_requirements:\n- name: Cryptography\n  version: 43.0.0\n"
    }
    paths = [
        "wheels/cryptography-43.0.0-cp39-abi3-manylinux2014_aarch64.whl",
        "wheels/cryptography-43.0.0-cp39-abi3-manylinux2014_x86_64.whl",
        "dev-wheels/pytest-8.3.5-py3-none-any.whl",
    ]
    inv = discover(files, paths)
    assert pins(inv) == {
        ("PyPI", "cryptography", "43.0.0"),
        ("PyPI", "pytest", "8.3.5"),
    }
    assert {d.scope for d in inv.dependencies if d.name == "pytest"} == {"development"}
    assert not inv.gaps


def test_requirements_include_hashes_markers_and_missing_local_wheels():
    inv = discover(
        {
            "requirements.txt": '-r requirements/base.txt\nrequests==2.31.0 \\\n  --hash=sha256:abcd\ncolorama==0.4.6; sys_platform == "win32"\n',
            "requirements/base.txt": "urllib3==1.26.18\n",
            "requirements-dev.txt": "./dev-wheels/pytest-8.3.5-py3-none-any.whl\n",
        },
        [],
    )
    assert pins(inv) == {
        ("PyPI", "requests", "2.31.0"),
        ("PyPI", "urllib3", "1.26.18"),
        ("PyPI", "colorama", "0.4.6"),
        ("PyPI", "pytest", "8.3.5"),
    }
    assert not inv.gaps


def test_unpinned_and_remote_requirements_are_explicit_gaps():
    inv = discover(
        {
            "requirements.txt": "httpx>=0.27\nfoo @ https://example.org/foo.whl\n-r missing.txt\n"
        },
        [],
    )
    assert ("PyPI", "httpx", "") in pins(inv)
    assert len(inv.gaps) == 3
    assert not any(d.name == "foo" for d in inv.dependencies)


def test_pyproject_and_locks_keep_optional_and_platform_dependencies():
    inv = discover(
        {
            "pyproject.toml": '[project]\ndependencies=["httpx>=0.27"]\n'
            '[project.optional-dependencies]\nimage=["pillow==10.0.0"]\n'
            '[build-system]\nrequires=["setuptools==70.0.0"]\n',
            "uv.lock": '[[package]]\nname="httpx"\nversion="0.27.0"\n'
            'source={registry="https://pypi.org/simple"}\n'
            '[[package]]\nname="local-project"\nversion="1.0.0"\nsource={editable="."}\n',
            "poetry.lock": '[[package]]\nname="urllib3"\nversion="2.2.0"\ngroups=["dev"]\n',
        },
        [],
    )
    assert ("PyPI", "httpx", "0.27.0") in pins(inv)
    assert ("PyPI", "pillow", "10.0.0") in pins(inv)
    assert not any(d.name == "local-project" for d in inv.dependencies)
    assert {d.scope for d in inv.dependencies if d.name == "setuptools"} == {"build"}
    assert {d.scope for d in inv.dependencies if d.name == "urllib3"} == {"development"}


def test_github_provenance_records_commit_and_version():
    inv = discover(
        {
            "toolbox-provenance.json": json.dumps(
                {
                    "source": "https://github.com/googleapis/mcp-toolbox",
                    "upstream_tag": "v1.3.0",
                    "upstream_commit": "a" * 40,
                }
            )
        },
        [],
    )
    assert pins(inv) == {("GitHub", "googleapis/mcp-toolbox", "v1.3.0")}
    assert inv.dependencies[0].commit == "a" * 40


@pytest.fixture(
    params=["scripts/build-config.json", "scripts/native-build-identities.json"]
)
def native_build_pin(request):
    if request.param == "scripts/build-config.json":
        data = {
            "source": "https://github.com/googleapis/mcp-toolbox",
            "upstream_tag": "v1.17.0",
            "upstream_commit": "45ed205cc8682ed066c82e0b65bcd0e8fc3becce",
            "tag": "v1.17.0",
            "commit": "45ed205cc8682ed066c82e0b65bcd0e8fc3becce",
            "packages": ["github.com/googleapis/mcp-toolbox/internal/sources/redis"],
            "module_lock": {"go.mod": "a" * 64, "go.sum": "b" * 64},
        }
    else:
        data = {
            "toolbox_tag": "v1.17.0",
            "toolbox_commit": "45ed205cc8682ed066c82e0b65bcd0e8fc3becce",
            "go.mod": "a" * 64,
            "go.sum": "b" * 64,
            "go_version": "go1.27.4",
        }
    return request.param, data


def test_fresh_native_source_retains_upstream_pin_without_generated_provenance(
    native_build_pin,
):
    path, data = native_build_pin
    tracked = {path: json.dumps(data), "extension.yaml": "python_requirements: []\n"}
    fetched = {p: text for p, text in tracked.items() if source_file(p)}
    inv = discover(fetched, list(tracked))
    assert pins(inv) == {("GitHub", "googleapis/mcp-toolbox", "v1.17.0")}
    dependency = inv.dependencies[0]
    assert dependency.commit == "45ed205cc8682ed066c82e0b65bcd0e8fc3becce"
    assert dependency.source == path
    assert dependency.scope == "upstream"
    assert not inv.gaps


def test_native_build_metadata_is_only_fetched_at_its_canonical_path():
    assert source_file("scripts/build-config.json")
    assert source_file("scripts/native-build-identities.json")
    for path in [
        "build-config.json", "other/build-config.json", "other/native-build-identities.json"
    ]:
        assert not source_file(path)
        assert not discover({path: "{}"}, [path]).dependencies


@pytest.mark.parametrize("value", ["", "latest", "v1", 17, None])
def test_native_build_pin_requires_an_exact_release_tag(native_build_pin, value):
    path, data = native_build_pin
    data["upstream_tag" if "upstream_tag" in data else "toolbox_tag"] = value
    inv = discover({path: json.dumps(data)}, [path])
    assert not inv.dependencies
    assert inv.gaps


@pytest.mark.parametrize("value", ["", "main", "a" * 39, 42, None])
def test_native_build_pin_requires_a_full_source_commit(native_build_pin, value):
    path, data = native_build_pin
    data["upstream_commit" if "upstream_commit" in data else "toolbox_commit"] = value
    inv = discover({path: json.dumps(data)}, [path])
    assert not inv.dependencies
    assert inv.gaps


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", "https://github.com/other/project"),
        ("tag", "v1.16.0"),
        ("commit", "c" * 40),
    ],
)
def test_toolbox_build_config_rejects_conflicting_upstream_identity(field, value):
    data = {
        "source": "https://github.com/googleapis/mcp-toolbox",
        "upstream_tag": "v1.17.0",
        "upstream_commit": "45ed205cc8682ed066c82e0b65bcd0e8fc3becce",
        field: value,
    }
    path = "scripts/build-config.json"
    inv = discover({path: json.dumps(data)}, [path])
    assert not inv.dependencies
    assert inv.gaps


@pytest.mark.parametrize(
    "field,value",
    [
        ("go.mod", ""),
        ("go.sum", "invalid"),
        ("source", "https://github.com/other/project"),
    ],
)
def test_implicit_toolbox_repository_requires_valid_native_identity_schema(field, value):
    data = {
        "toolbox_tag": "v1.17.0",
        "toolbox_commit": "45ed205cc8682ed066c82e0b65bcd0e8fc3becce",
        "go.mod": "a" * 64,
        "go.sum": "b" * 64,
        field: value,
    }
    path = "scripts/native-build-identities.json"
    inv = discover({path: json.dumps(data)}, [path])
    assert not inv.dependencies
    assert inv.gaps


@pytest.fixture
def driver_provenance():
    return {
        "source": "https://github.com/neo4j/neo4j-go-driver",
        "upstream_tag": "v6.4.0",
        "upstream_commit": "a" * 40,
        "module_sum": "h1:" + "A" * 43 + "=",
        "patch": "scripts/patches/driver.patch",
        "patch_sha256": "b" * 64,
        "upstream_module": {
            "ecosystem": "Go",
            "name": "github.com/neo4j/neo4j-go-driver/v6",
            "version": "v6.4.0",
        },
    }


def test_fork_provenance_supplements_advisories_without_hiding_local_gap(
    driver_provenance,
):
    inv = discover(
        {
            "neo4j-driver-provenance.json": json.dumps(driver_provenance),
            "go.mod": "module example.org/app\n"
            "require github.com/neo4j/neo4j-go-driver/v6 v6.4.0\n"
            "replace github.com/neo4j/neo4j-go-driver/v6 => /driver\n",
        },
        [driver_provenance["patch"]],
    )
    assert ("Go", "github.com/neo4j/neo4j-go-driver/v6", "v6.4.0") in pins(inv)
    assert ("GitHub", "neo4j/neo4j-go-driver", "v6.4.0") in pins(inv)
    assert any("local Go replacement" in gap for gap in inv.gaps)
    dep = next(d for d in inv.dependencies if d.ecosystem == "Go")
    assert dep.scope == "upstream"
    assert dep.source == "neo4j-driver-provenance.json"


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "github.com/other/driver/v6"),
        ("name", "github.com/neo4j/neo4j-go-driver/v7"),
        ("version", "v6.0.0"),
        ("version", "latest"),
        ("ecosystem", "npm"),
        ("module_sum", "h1:missing"),
        ("patch_sha256", "missing"),
        ("patch", "../driver.patch"),
        ("upstream_commit", ""),
    ],
)
def test_inconsistent_fork_identity_is_a_coverage_gap(driver_provenance, field, value):
    target = (
        driver_provenance["upstream_module"]
        if field in {"name", "version", "ecosystem"}
        else driver_provenance
    )
    target[field] = value
    inv = discover(
        {"neo4j-driver-provenance.json": json.dumps(driver_provenance)},
        ["scripts/patches/driver.patch"],
    )
    assert not any(d.ecosystem == "Go" for d in inv.dependencies)
    assert inv.gaps


def test_go_module_replacements_do_not_scan_replaced_version():
    inv = discover(
        {
            "go.mod": "module example.org/app\ngo 1.23.0\nrequire (\n"
            "example.org/old v1.0.0\nexample.org/lib v1.4.0 // indirect\n)\n"
            "replace example.org/old => example.org/fork v1.1.0\n"
        },
        [],
    )
    assert ("Go", "example.org/fork", "v1.1.0") in pins(inv)
    assert ("Go", "example.org/lib", "v1.4.0") in pins(inv)
    assert ("Go", "example.org/old", "v1.0.0") not in pins(inv)


def test_npm_lock_includes_transitive_scoped_packages_but_not_local_root():
    inv = discover(
        {
            "package-lock.json": json.dumps(
                {
                    "lockfileVersion": 3,
                    "packages": {
                        "": {"name": "my-app", "version": "1.0.0"},
                        "node_modules/@acme/thing": {"version": "1.2.3"},
                        "node_modules/a/node_modules/b": {
                            "version": "2.3.4",
                            "dev": True,
                        },
                    },
                }
            )
        },
        [],
    )
    assert pins(inv) == {("npm", "@acme/thing", "1.2.3"), ("npm", "b", "2.3.4")}


@pytest.mark.parametrize(
    "path,content",
    [
        ("extension.yaml", "python_requirements: wrong"),
        ("pyproject.toml", "[invalid"),
        ("package-lock.json", "{"),
    ],
)
def test_malformed_sources_do_not_abort_other_files(path, content):
    inv = discover({path: content, "requirements.txt": "requests==2.31.0"}, [])
    assert ("PyPI", "requests", "2.31.0") in pins(inv)
    assert any(path in gap for gap in inv.gaps)


def test_unsupported_manifests_are_visible_and_generated_copies_ignored():
    inv = discover(
        {}, ["yarn.lock", "Dockerfile", "dist/wheels/requests-1.0.0-py3-none-any.whl"]
    )
    assert not inv.dependencies
    assert any("yarn.lock" in gap for gap in inv.gaps)
    assert any("Dockerfile" in gap for gap in inv.gaps)


def test_private_registry_packages_are_not_misidentified_as_public_packages():
    inv = discover(
        {
            "requirements.txt": "--index-url https://packages.example.test/simple\nrequests==2.31.0\n",
            "package-lock.json": json.dumps(
                {
                    "lockfileVersion": 3,
                    "packages": {
                        "node_modules/axios": {
                            "version": "1.0.0",
                            "resolved": "git+ssh://git@example.test/private/axios#abc",
                        },
                        "node_modules/private": {
                            "version": "1.0.0",
                            "resolved": "https://packages.example.test/private.tgz",
                        },
                    },
                }
            ),
        },
        [],
    )
    assert not inv.dependencies
    assert len(inv.gaps) >= 3
