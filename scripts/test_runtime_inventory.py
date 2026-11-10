"""Runtime inventory uses verified payloads, never upstream module declarations."""

import hashlib
import io
import json
import stat
import struct
import zipfile

import pytest
from runtime_inventory import RuntimeAsset, inspect_runtime_archive


def varint(value):
    encoded = bytearray()
    while value >= 128:
        encoded.append((value & 127) | 128)
        value >>= 7
    return bytes(encoded) + bytes([value])


def elf(
    target="linux-amd64",
    modules="dep\texample.org/lib\tv1.2.3\th1:abc\n",
    flags=2,
    raw=None,
):
    """Construct the documented ELF64 Go build-info section without a compiler."""
    framed = (
        bytes.fromhex("3077af0c9274080241e1c107e6d618e6")
        + modules.encode()
        + bytes.fromhex("f932433186182072008242104116d8f2")
    )
    blob = b"\xff Go buildinf:" + bytes([8, flags]) + bytes(16)
    blob += (
        raw
        if raw is not None
        else varint(8) + b"go1.26.2" + varint(len(framed)) + framed
    )
    data = bytearray(256)
    data[:16] = b"\x7fELF\x02\x01\x01" + bytes(9)
    struct.pack_into(
        "<HHIQQQIHHHHHH",
        data,
        16,
        2,
        62 if target == "linux-amd64" else 183,
        1,
        0,
        64,
        128,
        0,
        64,
        56,
        1,
        64,
        2,
        0,
    )
    struct.pack_into(
        "<IIQQQQQQ", data, 64, 1, 6, 256, 4096, 4096, len(blob), len(blob), 16
    )
    # A name-less writable PROGBITS section; fallback data segment is supported.
    struct.pack_into(
        "<IIQQQQIIQQ", data, 192, 0, 1, 3, 4096, 256, len(blob), 0, 0, 16, 0
    )
    return bytes(data) + blob


def archive(files=None, target="linux-amd64", metadata=None, mode=None):
    files = dict(files or {})
    if target:
        files[".fs-package.yaml"] = json.dumps(
            metadata if metadata is not None else {"runtime_target": target}
        ).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
        for path, data in files.items():
            item = zipfile.ZipInfo("extension/" + path)
            item.external_attr = (mode or (stat.S_IFREG | 0o644)) << 16
            package.writestr(item, data)
    data = output.getvalue()
    return data, RuntimeAsset(
        target,
        "https://example.test/release.zip",
        hashlib.sha256(data).hexdigest(),
        len(data),
    )


def inspect(files=None, target="linux-amd64", **kwargs):
    return inspect_runtime_archive(*archive(files, target, **kwargs))


def pins(inv):
    return {(d.ecosystem, d.name, d.version) for d in inv.dependencies}


@pytest.mark.parametrize("target", ["linux-amd64", "linux-arm64"])
def test_binary_actual_dependencies_and_toolchain(target):
    inv = inspect({f"bin/{target}/toolbox": elf(target)}, target)
    assert pins(inv) == {
        ("Go", "example.org/lib", "v1.2.3"),
        ("Go", "stdlib", "1.26.2"),
    }
    assert {d.scope for d in inv.dependencies} == {f"runtime:{target}"}
    assert all(
        d.source.endswith(f"!/extension/bin/{target}/toolbox") for d in inv.dependencies
    )
    assert not inv.gaps


def test_replacements_use_shipped_fork_and_expose_local_replacement():
    inv = inspect(
        {
            "bin/linux-amd64/toolbox": elf(
                modules="dep\texample.org/old\tv1.0.0\n=>\texample.org/fork\tv2.0.0\th1:a\n\ndep\texample.org/local\tv1.0.0\n=>\t../local\t(devel)\t\n"
            )
        }
    )
    assert ("Go", "example.org/fork", "v2.0.0") in pins(inv)
    assert not any(
        d.name in {"example.org/old", "example.org/local", "../local"}
        for d in inv.dependencies
    )
    assert any("local" in gap for gap in inv.gaps)


@pytest.mark.parametrize(
    "modules",
    [
        "=>\texample.org/fork\tv1.0.0\n",
        "dep\ta.org/a\tv1.0.0\n=>\ta.org/b\tv1.0.0\n=>\ta.org/c\tv1.0.0\n",
        "dep\ta.org/a\tv1.0.0\ndep\ta.org/a\tv2.0.0\n",
    ],
)
def test_ambiguous_module_metadata_is_a_gap(modules):
    inv = inspect({"bin/linux-amd64/toolbox": elf(modules=modules)})
    assert inv.gaps
    assert not any(d.name.startswith("a.org") for d in inv.dependencies)


def test_architectures_keep_different_resolved_versions():
    amd = inspect({"bin/linux-amd64/a": elf()}, "linux-amd64")
    arm = inspect(
        {"bin/linux-arm64/a": elf("linux-arm64", "dep\texample.org/lib\tv1.3.0\n")},
        "linux-arm64",
    )
    assert ("Go", "example.org/lib", "v1.2.3") in pins(amd)
    assert ("Go", "example.org/lib", "v1.3.0") in pins(arm)


def test_universal_archives_scan_only_runtime_wheels_and_no_go_mod():
    inv = inspect(
        {
            "wheels/requests-2.32.4-py3-none-any.whl": b"",
            "dev-wheels/pytest-8.3.0-py3-none-any.whl": b"",
            "go.mod": b"require fake.org/not-shipped v1.0.0",
        },
        "",
    )
    assert pins(inv) == {("PyPI", "requests", "2.32.4")}
    assert not inv.gaps


def test_universal_native_files_have_explicit_gap():
    inv = inspect({"bin/linux-amd64/a": elf()}, "")
    assert not inv.dependencies
    assert any("universal" in gap for gap in inv.gaps)


@pytest.mark.parametrize("change", ["digest", "size", "limit"])
def test_archive_identity_and_size_are_verified(change):
    data, asset = archive()
    asset = RuntimeAsset(
        asset.target,
        asset.url,
        "0" * 64 if change == "digest" else asset.sha256,
        asset.size + 1
        if change == "size"
        else (51 * 1024 * 1024 if change == "limit" else asset.size),
    )
    with pytest.raises(ValueError):
        inspect_runtime_archive(data, asset)


@pytest.mark.parametrize(
    "path", ["../evil", "/absolute", "bin\\evil", "a/../../evil", "a//b", "C:/evil"]
)
def test_unsafe_archive_paths_are_rejected(path):
    with pytest.raises(ValueError, match="path"):
        inspect({path: b"bad"})


def test_symlink_and_zip_bomb_headers_are_rejected():
    with pytest.raises(ValueError, match="symlink|regular"):
        inspect({"link": b"elsewhere"}, mode=stat.S_IFLNK | 0o777)
    data, asset = archive({"huge": b"a"})
    mutable = bytearray(data)
    position = mutable.index(b"PK\x01\x02")
    struct.pack_into("<I", mutable, position + 24, 200 * 1024 * 1024)
    changed = bytes(mutable)
    with pytest.raises(ValueError, match="size|expansion"):
        inspect_runtime_archive(
            changed,
            RuntimeAsset(
                asset.target,
                asset.url,
                hashlib.sha256(changed).hexdigest(),
                len(changed),
            ),
        )


@pytest.mark.parametrize(
    "files,metadata",
    [
        ({"bin/linux-arm64/a": elf("linux-arm64")}, None),
        ({"bin/linux-amd64/a": elf("linux-arm64")}, None),
        ({}, {"runtime_target": "linux-arm64"}),
    ],
)
def test_target_mismatch_is_rejected(files, metadata):
    with pytest.raises(ValueError, match="target|architecture"):
        inspect(files, metadata=metadata)


@pytest.mark.parametrize("field", ["native_executable", "native_files", "provenance"])
def test_native_digest_and_size_are_verified(field):
    binary = elf()
    record = {"path": "bin/linux-amd64/a", "sha256": "0" * 64, "size": len(binary)}
    files = {record["path"]: binary}
    metadata = {"runtime_target": "linux-amd64"}
    if field == "provenance":
        files["toolbox-provenance.json"] = json.dumps(
            {"binaries": {"linux-amd64": record}}
        ).encode()
    else:
        metadata[field] = record if field == "native_executable" else [record]
    with pytest.raises(ValueError, match="SHA|digest|hash"):
        inspect(files, metadata=metadata)


@pytest.mark.parametrize(
    "binary,expected",
    [
        (b"native", "non-Go"),
        (elf(flags=0), "pointer"),
        (elf(raw=b"\x80" * 11), "varint"),
        (elf(raw=b"\xff" * 9 + b"\x02"), "varint"),
    ],
)
def test_unsupported_or_malformed_native_buildinfo_has_gap(binary, expected):
    inv = inspect({"bin/linux-amd64/a": binary})
    assert not inv.dependencies
    assert any(expected in gap for gap in inv.gaps)


def test_verified_native_metadata_and_provenance_preserve_dependencies():
    binary = elf()
    record = {
        "path": "bin/linux-amd64/a",
        "sha256": hashlib.sha256(binary).hexdigest(),
        "size": len(binary),
    }
    inv = inspect(
        {
            record["path"]: binary,
            "toolbox-provenance.json": json.dumps(
                {"binaries": {"linux-amd64": record}}
            ).encode(),
        },
        metadata={
            "runtime_target": "linux-amd64",
            "native_files": {record["path"]: record["sha256"]},
        },
    )
    assert ("Go", "example.org/lib", "v1.2.3") in pins(inv)
    assert not inv.gaps


def test_provenance_size_mismatch_is_rejected():
    binary = elf()
    record = {
        "path": "bin/linux-amd64/a",
        "sha256": hashlib.sha256(binary).hexdigest(),
        "size": len(binary) + 1,
    }
    with pytest.raises(ValueError, match="size"):
        inspect(
            {
                record["path"]: binary,
                "toolbox-provenance.json": json.dumps(
                    {"binaries": {"linux-amd64": record}}
                ).encode(),
            }
        )


def test_elf_named_section_and_big_endian_inline_metadata():
    binary = bytearray(elf("linux-arm64"))
    blob = binary[256:]
    names = b"\0.go.buildinfo\0.shstrtab\0"
    binary = binary[:256] + names + b"\0" * (32 - len(names)) + blob
    binary[5] = 2
    struct.pack_into(
        ">HHIQQQIHHHHHH", binary, 16, 2, 183, 1, 0, 64, 128, 0, 64, 56, 1, 64, 2, 1
    )
    struct.pack_into(
        ">IIQQQQQQ", binary, 64, 1, 6, 288, 4096, 4096, len(blob), len(blob), 16
    )
    struct.pack_into(
        ">IIQQQQIIQQ", binary, 128, 1, 1, 3, 4096, 288, len(blob), 0, 0, 16, 0
    )
    struct.pack_into(
        ">IIQQQQIIQQ", binary, 192, 15, 3, 0, 0, 256, len(names), 0, 0, 1, 0
    )
    inv = inspect({"bin/linux-arm64/a": bytes(binary)}, "linux-arm64")
    assert ("Go", "example.org/lib", "v1.2.3") in pins(inv)
    assert not inv.gaps


def test_truncated_elf_table_is_an_explicit_gap():
    inv = inspect({"bin/linux-amd64/a": elf()[:80]})
    assert inv.gaps
    assert not inv.dependencies


@pytest.mark.parametrize("provenance", [[], {"binaries": []}])
def test_invalid_provenance_shape_is_rejected(provenance):
    with pytest.raises(ValueError):
        inspect({"toolbox-provenance.json": json.dumps(provenance).encode()})


def test_universal_root_bin_directory_is_not_stripped_as_package_wrapper():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as package:
        package.writestr("bin/tool", b"unsupported executable")
    data = output.getvalue()
    inv = inspect_runtime_archive(
        data,
        RuntimeAsset(
            "",
            "https://example.test/a.zip",
            hashlib.sha256(data).hexdigest(),
            len(data),
        ),
    )
    assert any("universal" in gap for gap in inv.gaps)
