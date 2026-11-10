"""Inspect ZIPs statically; Go format: https://go.dev/src/debug/buildinfo/buildinfo.go."""

from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import struct
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

import yaml
from dependency_inventory import Dependency, Inventory
from packaging.utils import parse_wheel_filename

MAX_ARCHIVE = 50 * 1024 * 1024
MAX_EXPANDED = 150 * 1024 * 1024
MAX_FILE = 100 * 1024 * 1024
MAX_METADATA = 1024 * 1024
MACHINES = {"linux-amd64": 62, "linux-arm64": 183}
MAGIC = b"\xff Go buildinf:"
START = bytes.fromhex("3077af0c9274080241e1c107e6d618e6")
END = bytes.fromhex("f932433186182072008242104116d8f2")


@dataclass(frozen=True)
class RuntimeAsset:
    """Published catalog identity and trusted byte identity for one release asset."""

    target: str
    url: str
    sha256: str
    size: int


def _path(name):
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or "\x00" in name
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in name.rstrip("/").split("/"))
        or ":" in name
    ):
        raise ValueError(f"unsafe archive path: {name!r}")


def _read(archive, item, limit=MAX_FILE):
    if item.file_size > limit:
        raise ValueError(f"archive file size limit: {item.filename}")
    with archive.open(item) as stream:
        data = stream.read(limit + 1)
    if len(data) != item.file_size or len(data) > limit:
        raise ValueError(f"archive file size mismatch: {item.filename}")
    return data


def _records(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        if "path" in value:
            return [value]
        return [
            dict(record, path=path)
            if isinstance(record, dict)
            else {"path": path, "sha256": record}
            for path, record in value.items()
        ]
    raise ValueError("invalid native file metadata")


def _verify_record(record, files, archive):
    if not isinstance(record, dict) or record.get("path") not in files:
        raise ValueError("native file metadata path missing from archive")
    data = _read(archive, files[record["path"]])
    if (
        not isinstance(record.get("sha256"), str)
        or hashlib.sha256(data).hexdigest() != record["sha256"].lower()
    ):
        raise ValueError("native SHA-256 digest mismatch")
    if "size" in record and (
        type(record["size"]) is not int or len(data) != record["size"]
    ):
        raise ValueError("native file size mismatch")


def inspect_runtime_archive(data: bytes, asset: RuntimeAsset) -> Inventory:
    """Return shipped pins/gaps; reject unsafe, unverified or mistargeted archives."""
    if asset.target not in {"", *MACHINES}:
        raise ValueError("unsupported runtime target")
    if (
        type(asset.size) is not int
        or not 0 < asset.size <= MAX_ARCHIVE
        or len(data) != asset.size
        or not re.fullmatch(r"[0-9a-fA-F]{64}", asset.sha256)
        or hashlib.sha256(data).hexdigest() != asset.sha256.lower()
    ):
        raise ValueError("runtime archive SHA-256 or size mismatch/limit")
    result = Inventory()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            items = archive.infolist()
            if len(items) > 10000 or sum(i.file_size for i in items) > MAX_EXPANDED:
                raise ValueError("archive expansion size limit")
            names = set()
            for item in items:
                _path(item.filename)
                mode = item.external_attr >> 16
                if stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise ValueError("archive symlink/non-regular file")
                if (
                    item.filename in names
                    or item.file_size > MAX_FILE
                    or item.flag_bits & 1
                ):
                    raise ValueError(
                        "duplicate/encrypted archive path or file size limit"
                    )
                names.add(item.filename)
            actual = {i.filename: i for i in items if not i.is_dir()}
            package_paths = [
                p for p in actual if PurePosixPath(p).name == ".fs-package.yaml"
            ]
            if asset.target and len(package_paths) != 1:
                raise ValueError("target archive needs one .fs-package.yaml")
            prefix = (
                str(PurePosixPath(package_paths[0]).parent) + "/"
                if package_paths
                else ""
            )
            if prefix == "./":
                prefix = ""
            if not prefix and actual:
                roots = {p.split("/")[0] for p in actual}
                if roots & {"bin", "wheels", "dev-wheels"}:
                    roots.clear()
                if len(roots) == 1 and all("/" in p for p in actual):
                    prefix = next(iter(roots)) + "/"
            if any(not p.startswith(prefix) for p in actual):
                raise ValueError("archive path outside package root")
            files = {p.removeprefix(prefix): item for p, item in actual.items()}
            metadata = {}
            if package_paths:
                metadata = yaml.safe_load(
                    _read(archive, actual[package_paths[0]], MAX_METADATA)
                )
                if (
                    not isinstance(metadata, dict)
                    or metadata.get("runtime_target", "") != asset.target
                ):
                    raise ValueError("package runtime target mismatch")
            for key in ("native_files", "native_executable"):
                if key in metadata:
                    for record in _records(metadata[key]):
                        _verify_record(record, files, archive)
            for path, item in files.items():
                if path.endswith("-provenance.json"):
                    provenance = json.loads(_read(archive, item, MAX_METADATA))
                    if not isinstance(provenance, dict):
                        raise ValueError("invalid provenance object")
                    binaries = provenance.get("binaries", {})
                    if not isinstance(binaries, dict):
                        raise ValueError("invalid provenance binaries")
                    if asset.target in binaries:
                        _verify_record(binaries[asset.target], files, archive)
            for path, item in files.items():
                source = f"{asset.url}!/{item.filename}"
                scope = f"runtime:{asset.target}" if asset.target else "runtime"
                if (
                    path.endswith(".whl")
                    and "dev-wheels" not in PurePosixPath(path).parts
                ):
                    name, version, _, _ = parse_wheel_filename(PurePosixPath(path).name)
                    result.dependencies.append(
                        Dependency("PyPI", name, str(version), source, scope)
                    )
                with archive.open(item) as stream:
                    header = stream.read(20)
                native = (
                    path.startswith("bin/")
                    or header.startswith(b"\x7fELF")
                    or re.search(r"\.(so(?:\.[0-9.]+)?|dll|dylib)$", path)
                )
                if not native:
                    continue
                if not asset.target:
                    result.gaps.append(
                        f"{source}: native file in universal archive cannot be assigned a runtime target"
                    )
                    continue
                if not path.startswith(f"bin/{asset.target}/"):
                    raise ValueError("native file path does not match runtime target")
                if header.startswith(b"\x7fELF"):
                    if len(header) < 20 or header[4:6] not in {
                        b"\x02\x01",
                        b"\x02\x02",
                    }:
                        result.gaps.append(f"{source}: unsupported ELF format")
                        continue
                    endian = "little" if header[5] == 1 else "big"
                    if int.from_bytes(header[18:20], endian) != MACHINES[asset.target]:
                        raise ValueError(
                            "ELF architecture does not match runtime target"
                        )
                try:
                    version, modules = _buildinfo(_read(archive, item))
                    if re.fullmatch(r"go\d+\.\d+(?:\.\d+)?", version):
                        result.dependencies.append(
                            Dependency("Go", "stdlib", version[2:], source, scope)
                        )
                    else:
                        result.gaps.append(
                            f"{source}: Go toolchain version cannot be mapped reliably: {version}"
                        )
                    for name, version in _modules(modules, result.gaps, source):
                        result.dependencies.append(
                            Dependency("Go", name, version, source, scope)
                        )
                except (ValueError, UnicodeError, struct.error) as exc:
                    result.gaps.append(f"{source}: {exc}")
    except (
        zipfile.BadZipFile,
        yaml.YAMLError,
        UnicodeError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        NotImplementedError,
        RuntimeError,
    ) as exc:
        raise ValueError("invalid runtime archive metadata/content") from exc
    result.dependencies = sorted(set(result.dependencies))
    result.gaps = sorted(set(result.gaps))
    return result


def _buildinfo(data):
    if len(data) < 64 or data[:4] != b"\x7fELF":
        raise ValueError("non-Go native file cannot be inspected")
    order = "<" if data[5] == 1 else ">"
    phoff, shoff = struct.unpack_from(order + "QQ", data, 32)
    phsize, phnum, shsize, shnum, strindex = struct.unpack_from(
        order + "HHHHH", data, 54
    )
    if (
        phnum > 4096
        or shnum > 4096
        or (phnum and phsize != 56)
        or (shnum and shsize != 64)
    ):
        raise ValueError("unsupported ELF header table")
    sections = []
    for index in range(shnum):
        sections.append(
            struct.unpack_from(order + "IIQQQQIIQQ", data, shoff + index * shsize)
        )
    regions = []
    if sections and strindex < len(sections):
        strings = sections[strindex]
        names = data[strings[4] : strings[4] + strings[5]]
        for section in sections:
            if names[section[0] :].split(b"\0", 1)[0] == b".go.buildinfo":
                regions = [(section[4], section[5], section[3])]
                break
    if not regions:
        for index in range(phnum):
            kind, flags, offset, address, _, size, _, _ = struct.unpack_from(
                order + "IIQQQQQQ", data, phoff + index * phsize
            )
            if kind == 1 and flags & 3 == 2:
                regions = [(offset, size, address)]
                break
    if not regions:
        raise ValueError("non-Go native file: no Go build-info section/data segment")
    offset, size, address = regions[0]
    if offset + size > len(data):
        raise ValueError("ELF build-info range exceeds file")
    region = data[offset : offset + size]
    cursor = (-address) % 16
    while cursor + 32 <= len(region) and region[cursor : cursor + 14] != MAGIC:
        cursor += 16
    if cursor + 32 > len(region):
        raise ValueError("non-Go native file: Go build metadata absent")
    if region[cursor + 15] & 2 == 0:
        raise ValueError("unsupported Go pointer build-info format (pre-1.18)")
    cursor += 32

    def string():
        nonlocal cursor
        length = 0
        for index in range(10):
            if cursor >= len(region):
                raise ValueError("truncated Go build-info varint")
            byte = region[cursor]
            cursor += 1
            if index == 9 and byte > 1:
                raise ValueError("overflow Go build-info varint")
            length |= (byte & 127) << (index * 7)
            if byte < 128:
                break
        else:
            raise ValueError("malformed Go build-info varint")
        if length > MAX_METADATA or cursor + length > len(region):
            raise ValueError("Go build-info string size exceeds bounds")
        value = region[cursor : cursor + length]
        cursor += length
        return value

    version, modules = string().decode(), string()
    if not (modules.startswith(START) and modules.endswith(END)):
        raise ValueError("Go module build-info framing missing")
    return version, modules[16:-16].decode()


def _modules(content, gaps, source):
    records, current = [], None
    for line in content.splitlines():
        fields = line.split("\t")
        if fields[0] in {"dep", "mod"}:
            if len(fields) not in {3, 4}:
                raise ValueError("malformed Go module record")
            current = [fields[1], fields[2], False, fields[0]]
            records.append(current)
        elif fields[0] == "=>":
            if current is None or current[2] or len(fields) not in {3, 4}:
                raise ValueError("ambiguous Go module replacement")
            current[:3] = [fields[1], fields[2], True]
        elif line and fields[0] not in {"path", "build"}:
            raise ValueError("unknown Go build-info record")
    resolved = {}
    for name, version, replaced, kind in records:
        if kind == "mod" and version == "(devel)" and not replaced:
            continue
        if not re.fullmatch(
            r"v\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.+-]+)?", version
        ) or name.startswith((".", "/")):
            gaps.append(
                f"{source}: local/unversioned Go replacement or module {name} cannot be version-checked"
            )
            continue
        if name in resolved:
            raise ValueError("ambiguous duplicate Go module records")
        resolved[name] = version
    return sorted(resolved.items())
