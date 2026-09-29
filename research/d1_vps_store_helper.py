#!/usr/bin/env python3
"""Repository-owned durable store helper for the SETUP_01 D1 Ubuntu VPS.

This file is the only artifact that runs on the VPS.  It is deliberately
standard-library only, streams every payload instead of loading the store into
memory, and exposes no overwrite or delete operation for formal evidence.

It is *not* a service: GitHub Actions invokes it non-interactively over SSH,
one bounded command at a time.  All D1 identity, protocol and activation logic
stays in the repository modules; this helper only performs byte-level
create-only storage, hash verification and read-back.

Deployed path (frozen): /srv/d1-research/system/d1_vps_store_helper.py
"""
from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sys
import time
from uuid import uuid4


HELPER_VERSION = "D1_VPS_STORE_HELPER_V1"
BACKEND_IDENTITY = "SETUP01_D1_VPS_SSH_DURABLE_STORAGE"
BACKEND_VERSION = "VPS_D1_DURABLE_BACKEND_V1"
STORAGE_IDENTITY_SCHEMA = "setup01-d1-vps-storage-identity-v1"
DEFAULT_STORAGE_ROOT = "/srv/d1-research"

# Only derived, non-evidence artifacts may be replaced.  Formal evidence
# (objects/, sessions/, system/activation/, system/activation_epochs/) is
# create-only for ever.
DERIVED_REPLACE_PREFIXES = ("manifests/",)
EVIDENCE_PREFIXES = (
    "objects/",
    "sessions/",
    "system/activation/",
    "system/activation_epochs/",
    "system/validation/",
)
TMP_PREFIX = "system/tmp/"
STALE_PART_SECONDS = 6 * 3600

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_CONFLICT = 3
EXIT_HASH_MISMATCH = 4
EXIT_LOW_SPACE = 5
EXIT_INTEGRITY = 6

CHUNK = 1 << 20


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def storage_identity_sha256(storage_root: str) -> str:
    """Identity of the *storage* (not the transport) frozen by activation."""

    return sha256(canonical_bytes({
        "schema_version": STORAGE_IDENTITY_SCHEMA,
        "backend_identity": BACKEND_IDENTITY,
        "backend_version": BACKEND_VERSION,
        "storage_root": str(storage_root),
    })).hexdigest()


def _emit(value: object) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.flush()


def _emit_stderr(value: object) -> None:
    sys.stderr.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stderr.flush()


def _fail(code: int, reason: str, **extra: object) -> "None":
    payload = {"status": "FAIL_CLOSED", "reason": reason, "helper_version": HELPER_VERSION}
    payload.update(extra)
    sys.stderr.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stderr.flush()
    raise SystemExit(code)


def resolve_root(value: str) -> Path:
    root = Path(value)
    if not root.is_absolute():
        _fail(EXIT_USAGE, "D1_VPS_STORAGE_ROOT_MUST_BE_ABSOLUTE", storage_root=str(root))
    resolved = Path(os.path.realpath(root))
    if not resolved.is_dir():
        _fail(EXIT_INTEGRITY, "D1_VPS_STORAGE_ROOT_MISSING", storage_root=str(resolved))
    return resolved


def resolve_name(root: Path, name: str) -> Path:
    text = str(name or "").strip()
    if not text or text.startswith("/") or "\\" in text:
        _fail(EXIT_USAGE, "D1_REMOTE_PATH_OUTSIDE_STORE", name=text)
    parts = text.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        _fail(EXIT_USAGE, "D1_REMOTE_PATH_OUTSIDE_STORE", name=text)
    if text.startswith(TMP_PREFIX):
        _fail(EXIT_USAGE, "D1_REMOTE_PATH_OUTSIDE_STORE", name=text)
    candidate = root.joinpath(*parts)
    # Reject a symlinked parent directory that escapes the store root.
    resolved_parent = Path(os.path.realpath(str(candidate.parent)))
    if resolved_parent != root and root not in resolved_parent.parents:
        _fail(EXIT_USAGE, "D1_REMOTE_PATH_OUTSIDE_STORE", name=text)
    return candidate


def hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def free_bytes(root: Path) -> int:
    return int(shutil.disk_usage(str(root)).free)


def _fsync_directory(path: Path) -> None:
    try:
        handle = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(handle)
    except OSError:
        pass
    finally:
        os.close(handle)


def _cleanup_stale_parts(tmp_dir: Path) -> None:
    cutoff = time.time() - STALE_PART_SECONDS
    try:
        entries = list(tmp_dir.iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            continue


def _iter_store_files(root: Path):
    for directory in (
        "objects",
        "sessions",
        "system/activation",
        "system/activation_epochs",
        "system/validation",
        "manifests",
    ):
        base = root / directory
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                yield path


def _store_stats(root: Path) -> dict:
    store_bytes = 0
    object_count = 0
    object_bytes = 0
    session_counts = {"CN": 0, "US": 0}
    activations: list[str] = []
    for path in _iter_store_files(root):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        relative = path.relative_to(root).as_posix()
        store_bytes += size
        if relative.startswith("objects/"):
            object_count += 1
            object_bytes += size
        elif relative.startswith("sessions/CN/"):
            session_counts["CN"] += 1
        elif relative.startswith("sessions/US/"):
            session_counts["US"] += 1
        elif relative.startswith("system/activation/"):
            activations.append(relative)
        elif relative.startswith("system/activation_epochs/"):
            activations.append(relative)
    return {
        "store_bytes": store_bytes,
        "object_count": object_count,
        "object_bytes": object_bytes,
        "session_counts": session_counts,
        "activation_records": sorted(activations),
    }


def cmd_identity(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    _emit({
        "status": "IDENTITY_VERIFIED",
        "backend_identity": BACKEND_IDENTITY,
        "backend_version": BACKEND_VERSION,
        "helper_version": HELPER_VERSION,
        "configured_root": str(args.root),
        "storage_root": str(root),
        "storage_identity_sha256": storage_identity_sha256(str(root)),
        "python_version": sys.version.split()[0],
    })
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    usage = shutil.disk_usage(str(root))
    stats = _store_stats(root)
    free = int(usage.free)
    payload = {
        "status": "STORAGE_STATUS",
        "backend_identity": BACKEND_IDENTITY,
        "backend_version": BACKEND_VERSION,
        "helper_version": HELPER_VERSION,
        "storage_root": str(root),
        "storage_identity_sha256": storage_identity_sha256(str(root)),
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_bytes": int(usage.total),
        "used_bytes": int(usage.used),
        "free_bytes": free,
        "min_free_bytes": int(args.min_free_bytes),
        "danger_free_bytes": int(args.danger_free_bytes),
        "low_space": free < int(args.min_free_bytes),
        "low_space_danger": free < int(args.danger_free_bytes),
        **stats,
    }
    payload["space_status"] = (
        "D1_STORAGE_LOW_SPACE_FAIL_CLOSED" if payload["low_space_danger"]
        else "D1_STORAGE_LOW_SPACE" if payload["low_space"]
        else "D1_STORAGE_OK"
    )
    _emit(payload)
    return EXIT_OK


def cmd_put(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    target = resolve_name(root, args.name)
    expected = str(args.sha256 or "").strip().lower()
    if len(expected) != 64:
        _fail(EXIT_USAGE, "D1_EXPECTED_SHA256_REQUIRED", name=args.name)
    derived = bool(getattr(args, "derived_replace", False))
    if derived and not str(args.name).startswith(DERIVED_REPLACE_PREFIXES):
        _fail(EXIT_USAGE, "D1_DERIVED_REPLACE_NOT_ALLOWED", name=args.name)
    if free_bytes(root) < int(args.danger_free_bytes):
        _fail(EXIT_LOW_SPACE, "D1_STORAGE_LOW_SPACE_FAIL_CLOSED", name=args.name)

    tmp_dir = root / "system" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_stale_parts(tmp_dir)
    tmp_path = tmp_dir / f"{uuid4().hex}.part"
    digest = sha256()
    size = 0
    try:
        with tmp_path.open("xb") as handle:
            while True:
                chunk = sys.stdin.buffer.read(CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        actual = digest.hexdigest()
        if actual != expected:
            _fail(
                EXIT_HASH_MISMATCH,
                "D1_TRANSFER_HASH_MISMATCH",
                name=args.name,
                received_sha256=actual,
                expected_sha256=expected,
                received_bytes=size,
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        status = "CREATED"
        if derived:
            existed = target.is_file()
            if (
                existed
                and target.stat().st_size == size
                and hash_file(target) == actual
            ):
                status = "IDEMPOTENT_REPLAY"
            else:
                os.replace(tmp_path, target)
                status = "REPLACED_DERIVED" if existed else "CREATED"
        else:
            try:
                os.link(tmp_path, target)
            except FileExistsError:
                existing_size = target.stat().st_size
                existing_sha = hash_file(target)
                if existing_sha == actual and existing_size == size:
                    status = "IDEMPOTENT_REPLAY"
                else:
                    _fail(
                        EXIT_CONFLICT,
                        "D1_CREATE_ONLY_CONFLICT",
                        name=args.name,
                        existing_sha256=existing_sha,
                        incoming_sha256=actual,
                    )
        _fsync_directory(target.parent)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    _emit({
        "status": status,
        "backend_identity": BACKEND_IDENTITY,
        "backend_version": BACKEND_VERSION,
        "helper_version": HELPER_VERSION,
        "name": args.name,
        "sha256": expected,
        "size": size,
        "role": str(args.role),
        "market": (str(args.market).upper() if args.market else None),
        "session_date": args.session,
        "protocol_version": args.protocol,
        "storage_root": str(root),
        "storage_identity_sha256": storage_identity_sha256(str(root)),
        "free_bytes": free_bytes(root),
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    return EXIT_OK


def cmd_read(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    path = resolve_name(root, args.name)
    if not path.is_file():
        _fail(EXIT_INTEGRITY, "D1_REMOTE_OBJECT_MISSING", name=args.name)
    size = path.stat().st_size
    if args.sha256:
        actual = hash_file(path)
        if actual != str(args.sha256).strip().lower():
            _fail(
                EXIT_INTEGRITY,
                "D1_REMOTE_OBJECT_HASH_MISMATCH",
                name=args.name,
                stored_sha256=actual,
                expected_sha256=str(args.sha256).strip().lower(),
            )
    digest = sha256()
    out = sys.stdout.buffer
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            out.write(chunk)
    out.flush()
    sys.stderr.write(json.dumps({
        "status": "READ_BACK",
        "name": args.name,
        "sha256": digest.hexdigest(),
        "size": size,
        "backend_version": BACKEND_VERSION,
        "helper_version": HELPER_VERSION,
        "storage_root": str(root),
        "storage_identity_sha256": storage_identity_sha256(str(root)),
    }, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stderr.flush()
    return EXIT_OK


def cmd_stat(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    path = resolve_name(root, args.name)
    if not path.is_file():
        _emit({
            "status": "MISSING",
            "name": args.name,
            "exists": False,
            "backend_version": BACKEND_VERSION,
            "helper_version": HELPER_VERSION,
            "storage_root": str(root),
            "storage_identity_sha256": storage_identity_sha256(str(root)),
        })
        return EXIT_OK
    _emit({
        "status": "PRESENT",
        "name": args.name,
        "exists": True,
        "sha256": hash_file(path),
        "size": path.stat().st_size,
        "backend_version": BACKEND_VERSION,
        "helper_version": HELPER_VERSION,
        "storage_root": str(root),
        "storage_identity_sha256": storage_identity_sha256(str(root)),
    })
    return EXIT_OK


def _scan_entries(root: Path, prefix: str, *, with_hash: bool) -> list:
    entries = []
    for path in _iter_store_files(root):
        relative = path.relative_to(root).as_posix()
        if prefix and not relative.startswith(prefix):
            continue
        entry = {"name": relative, "size": path.stat().st_size}
        if with_hash:
            entry["sha256"] = hash_file(path)
        entries.append(entry)
    entries.sort(key=lambda item: item["name"])
    return entries


def cmd_scan(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    entries = _scan_entries(root, str(args.prefix or ""), with_hash=bool(args.hash))
    _emit({
        "status": "SCANNED",
        "prefix": str(args.prefix or ""),
        "hashed": bool(args.hash),
        "backend_version": BACKEND_VERSION,
        "helper_version": HELPER_VERSION,
        "storage_root": str(root),
        "storage_identity_sha256": storage_identity_sha256(str(root)),
        "count": len(entries),
        "entries": entries,
    })
    return EXIT_OK


def cmd_cat_many(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    limit = int(args.max_bytes)
    out = sys.stdout
    count = 0
    for path in _iter_store_files(root):
        relative = path.relative_to(root).as_posix()
        if not relative.startswith(str(args.prefix)):
            continue
        size = path.stat().st_size
        if size > limit:
            _fail(
                EXIT_INTEGRITY,
                "D1_CAT_MANY_FILE_TOO_LARGE",
                name=relative,
                size=size,
                max_bytes=limit,
            )
        payload = path.read_bytes()
        out.write(json.dumps({
            "name": relative,
            "size": size,
            "sha256": sha256(payload).hexdigest(),
            "payload_b64": base64.b64encode(payload).decode("ascii"),
        }, ensure_ascii=False, sort_keys=True) + "\n")
        count += 1
    out.flush()
    # The data stream owns stdout; the completion receipt goes to stderr.
    _emit_stderr({
        "status": "CAT_MANY_COMPLETE",
        "prefix": str(args.prefix),
        "count": count,
        "backend_version": BACKEND_VERSION,
        "helper_version": HELPER_VERSION,
        "storage_root": str(root),
        "storage_identity_sha256": storage_identity_sha256(str(root)),
    })
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SETUP_01 D1 durable store helper")
    parser.add_argument("--root", default=os.environ.get("D1_VPS_STORAGE_ROOT", DEFAULT_STORAGE_ROOT))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("identity")

    status = sub.add_parser("status")
    status.add_argument("--min-free-bytes", type=int, default=1 << 30)
    status.add_argument("--danger-free-bytes", type=int, default=1 << 28)

    put = sub.add_parser("put")
    put.add_argument("--name", required=True)
    put.add_argument("--sha256", required=True)
    put.add_argument("--role", required=True)
    put.add_argument("--market")
    put.add_argument("--session")
    put.add_argument("--protocol")
    put.add_argument("--danger-free-bytes", type=int, default=1 << 28)
    put.add_argument("--derived-replace", action="store_true")

    read = sub.add_parser("read")
    read.add_argument("--name", required=True)
    read.add_argument("--sha256")

    stat = sub.add_parser("stat")
    stat.add_argument("--name", required=True)

    scan = sub.add_parser("scan")
    scan.add_argument("--prefix", default="")
    scan.add_argument("--hash", action="store_true")

    cat_many = sub.add_parser("cat-many")
    cat_many.add_argument("--prefix", required=True)
    cat_many.add_argument("--max-bytes", type=int, default=1 << 20)
    return parser


COMMANDS = {
    "identity": cmd_identity,
    "status": cmd_status,
    "put": cmd_put,
    "read": cmd_read,
    "stat": cmd_stat,
    "scan": cmd_scan,
    "cat-many": cmd_cat_many,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
