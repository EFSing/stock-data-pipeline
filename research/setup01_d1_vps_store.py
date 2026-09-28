"""Ubuntu VPS durable backend for SETUP_01 D1.

The store speaks to a dedicated non-root account over SSH and drives one
repository-owned, standard-library-only helper
(``research/d1_vps_store_helper.py``) with a single bounded command per
payload.  The VPS never pulls market data, never runs the pipeline, and never
sees holdings, Paper, production Sheet state or broker credentials.

Immutable semantics: byte payloads are create-only (``O_CREAT|O_EXCL`` via
``link`` after a fully streamed, fsynced temporary file), identical replay is
reported as ``IDEMPOTENT_REPLAY``, and a different payload under the same
identity fails closed.  Formal evidence has no update or delete path.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
import shlex
import subprocess
import tempfile
from typing import Any, BinaryIO, Callable, Mapping, Protocol, Sequence

from research.setup01_d1_activation import (
    build_activation_record,
    session_is_in_activation_window,
    validate_activation_record,
)
from research.setup01_d1_prospective import (
    D1IntegrityError,
    FilesystemD1Store,
    PROTOCOL_VERSION,
    canonical_bytes,
    content_sha256,
    validate_session_snapshot,
    verify_frozen_protocol,
)
from research.setup01_d1_source_contract import D1_SOURCE_CONTRACT_VERSION


VPS_BACKEND_IDENTITY = "SETUP01_D1_VPS_SSH_DURABLE_STORAGE"
VPS_BACKEND_VERSION = "VPS_D1_DURABLE_BACKEND_V1"
VPS_HELPER_VERSION = "D1_VPS_STORE_HELPER_V1"
VPS_STORAGE_IDENTITY_SCHEMA = "setup01-d1-vps-storage-identity-v1"
VPS_POINTER_SCHEMA_VERSION = "setup01-d1-session-commit-vps-v1"
VPS_MANIFEST_SCHEMA_VERSION = "setup01-d1-store-manifest-v1"
VPS_MANIFEST_NAME = "manifests/store-manifest-v1.json"
DEFAULT_VPS_STORAGE_ROOT = "/srv/d1-research"
DEFAULT_VPS_HELPER_PATH = "/srv/d1-research/system/d1_vps_store_helper.py"
DEFAULT_MIN_FREE_BYTES = 1 << 30
DEFAULT_DANGER_FREE_BYTES = 1 << 28
CAT_MANY_MAX_BYTES = 1 << 20
SYNTHETIC_CLASSIFICATION = "SYNTHETIC_VALIDATION_OBJECT_NOT_D1_EVIDENCE"

HELPER_EXIT_CONFLICT = 3
HELPER_EXIT_HASH_MISMATCH = 4
HELPER_EXIT_LOW_SPACE = 5
HELPER_EXIT_INTEGRITY = 6


class VpsCommandError(D1IntegrityError):
    """A bounded remote helper failure with its exit code and reason preserved."""

    def __init__(self, exit_code: int, reason: str, *, detail: Mapping[str, Any] | None = None):
        super().__init__(f"{reason} (helper exit {exit_code})")
        self.exit_code = int(exit_code)
        self.reason = str(reason)
        self.detail = dict(detail or {})


class VpsObjectMissing(VpsCommandError):
    pass


def storage_identity_sha256(storage_root: str) -> str:
    """Identity of the frozen D1 storage root (mirrors the remote helper)."""

    return sha256(canonical_bytes({
        "schema_version": VPS_STORAGE_IDENTITY_SCHEMA,
        "backend_identity": VPS_BACKEND_IDENTITY,
        "backend_version": VPS_BACKEND_VERSION,
        "storage_root": str(storage_root),
    })).hexdigest()


def _normalize_remote_root(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("D1_VPS_STORAGE_ROOT is required")
    if not (text.startswith("/") or os.path.isabs(text)):
        raise ValueError("D1_VPS_STORAGE_ROOT must be an absolute path")
    while len(text) > 1 and text.endswith(("/", "\\")):
        text = text[:-1]
    return text


def fingerprint_from_public_key(encoded: str) -> str:
    """Return the OpenSSH ``SHA256:`` fingerprint of a base64 public key blob."""

    try:
        blob = base64.b64decode(str(encoded).strip(), validate=True)
    except Exception as exc:  # noqa: BLE001 - every decode failure is a rejected pin
        raise ValueError("known_hosts public key is not valid base64") from exc
    digest = base64.b64encode(sha256(blob).digest()).decode("ascii").rstrip("=")
    return f"SHA256:{digest}"


def known_hosts_host_token(host: str, port: int) -> str:
    return str(host) if int(port) == 22 else f"[{host}]:{int(port)}"


def known_hosts_fingerprints(known_hosts: str, host: str, port: int) -> list[str]:
    """Extract the pinned host key fingerprints for one host:port entry."""

    token = known_hosts_host_token(host, port)
    found: list[str] = []
    for line in str(known_hosts).splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        fields = text.split()
        if fields[0].startswith("@"):
            fields = fields[1:]
        if len(fields) < 3:
            continue
        hosts = fields[0].split(",")
        if token not in hosts:
            continue
        found.append(fingerprint_from_public_key(fields[2]))
    return found


class VpsStoreRunner(Protocol):
    """Executes one helper command and returns ``(exit_code, stdout, stderr)``."""

    def __call__(
        self,
        command: Sequence[str],
        *,
        stdin: bytes | None = ...,
        stdout: BinaryIO | None = ...,
    ) -> tuple[int, bytes, bytes]: ...


@dataclass(frozen=True)
class VpsHop:
    """Frozen SSH transport identity for the D1 durable store."""

    host: str
    user: str
    storage_root: str
    identity_file: str
    known_hosts_path: str
    host_key_fingerprint: str
    port: int = 22
    helper_path: str = DEFAULT_VPS_HELPER_PATH
    python: str = "python3"
    connect_timeout: int = 20

    def __post_init__(self) -> None:
        for field_name, value in (
            ("host", self.host),
            ("user", self.user),
            ("storage_root", self.storage_root),
            ("identity_file", self.identity_file),
            ("known_hosts_path", self.known_hosts_path),
            ("host_key_fingerprint", self.host_key_fingerprint),
            ("helper_path", self.helper_path),
        ):
            if not str(value or "").strip():
                raise ValueError(f"D1 VPS hop {field_name} is required")
        if not str(self.host_key_fingerprint).startswith("SHA256:"):
            raise ValueError("D1_VPS_HOST_KEY_FINGERPRINT must be an OpenSSH SHA256 fingerprint")
        if int(self.port) <= 0:
            raise ValueError("D1_VPS_PORT must be a positive port")

    def ssh_argv(self, remote_command: str) -> list[str]:
        """Build a strictly host-key-verified non-interactive SSH invocation."""

        return [
            "ssh",
            "-p", str(int(self.port)),
            "-i", self.identity_file,
            "-o", f"UserKnownHostsFile={self.known_hosts_path}",
            "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", "StrictHostKeyChecking=yes",
            "-o", "UpdateHostKeys=no",
            "-o", "BatchMode=yes",
            "-o", "PasswordAuthentication=no",
            "-o", "KbdInteractiveAuthentication=no",
            "-o", "PreferredAuthentications=publickey",
            "-o", "IdentitiesOnly=yes",
            "-o", f"ConnectTimeout={int(self.connect_timeout)}",
            f"{self.user}@{self.host}",
            remote_command,
        ]

    def remote_command(self, command: Sequence[str]) -> str:
        tokens = [
            self.python,
            self.helper_path,
            "--root", self.storage_root,
            *[str(item) for item in command],
        ]
        return " ".join(shlex.quote(token) for token in tokens)

    def verify_known_hosts(self) -> str:
        """Fail closed unless the frozen fingerprint matches the pinned entry."""

        text = Path(self.known_hosts_path).read_text(encoding="utf-8")
        fingerprints = known_hosts_fingerprints(text, self.host, self.port)
        if not fingerprints:
            raise D1IntegrityError(
                f"D1_KNOWN_HOSTS_ENTRY_MISSING:{known_hosts_host_token(self.host, self.port)}"
            )
        if self.host_key_fingerprint not in fingerprints:
            raise D1IntegrityError("D1_KNOWN_HOSTS_FINGERPRINT_MISMATCH")
        return self.host_key_fingerprint

    def transport_identity(self) -> dict[str, Any]:
        return {
            "ssh_host": self.host,
            "ssh_port": int(self.port),
            "ssh_user": self.user,
            "ssh_host_key_fingerprint": self.host_key_fingerprint,
        }


class SshVpsRunner:
    """Runs one helper command per SSH connection with host-key verification."""

    def __init__(self, hop: VpsHop):
        self.hop = hop
        self.last_command: list[str] | None = None

    def __call__(
        self,
        command: Sequence[str],
        *,
        stdin: bytes | None = None,
        stdout: BinaryIO | None = None,
    ) -> tuple[int, bytes, bytes]:
        # The frozen host key is checked before every connection attempt.
        self.hop.verify_known_hosts()
        argv = self.hop.ssh_argv(self.hop.remote_command(command))
        self.last_command = argv
        completed = subprocess.run(
            argv,
            input=stdin,
            stdout=stdout if stdout is not None else subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        out = b"" if stdout is not None else bytes(completed.stdout or b"")
        return int(completed.returncode), out, bytes(completed.stderr or b"")


def _write_secret_file(content: str, *, prefix: str, mode: int) -> str:
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", prefix=prefix, delete=False, newline="\n"
    )
    try:
        handle.write(content if content.endswith("\n") else content + "\n")
    finally:
        handle.close()
    os.chmod(handle.name, mode)
    return handle.name


def hop_from_env(environ: Mapping[str, str] | None = None) -> VpsHop:
    """Build the SSH hop from GitHub Actions secrets (never logged)."""

    values = os.environ if environ is None else environ
    host = str(values.get("D1_VPS_HOST") or "").strip()
    if not host:
        raise RuntimeError("缺少 D1_VPS_HOST")
    known_hosts = str(values.get("D1_VPS_KNOWN_HOSTS") or "")
    if not known_hosts.strip():
        raise RuntimeError("缺少 D1_VPS_KNOWN_HOSTS")
    private_key = str(values.get("D1_VPS_SSH_PRIVATE_KEY") or "")
    if not private_key.strip():
        raise RuntimeError("缺少 D1_VPS_SSH_PRIVATE_KEY")
    host_key_fingerprint = str(values.get("D1_VPS_HOST_KEY_FINGERPRINT") or "").strip()
    if not host_key_fingerprint:
        raise RuntimeError("缺少 D1_VPS_HOST_KEY_FINGERPRINT")
    storage_root = _normalize_remote_root(
        str(values.get("D1_VPS_STORAGE_ROOT") or DEFAULT_VPS_STORAGE_ROOT)
    )
    if not storage_root.startswith("/"):
        raise ValueError("D1_VPS_STORAGE_ROOT must be an absolute POSIX path")
    return VpsHop(
        host=host,
        user=str(values.get("D1_VPS_USER") or "d1store").strip(),
        storage_root=storage_root,
        identity_file=_write_secret_file(private_key, prefix="d1-vps-key-", mode=0o600),
        known_hosts_path=_write_secret_file(known_hosts, prefix="d1-vps-known-", mode=0o644),
        host_key_fingerprint=host_key_fingerprint,
        port=int(str(values.get("D1_VPS_PORT") or "22").strip() or "22"),
        helper_path=str(values.get("D1_VPS_HELPER_PATH") or DEFAULT_VPS_HELPER_PATH).strip(),
    )


@dataclass(frozen=True)
class VpsCommitResult:
    status: str
    event_id: str
    event_sha256: str
    object_name: str
    object_sha256: str
    object_bytes: int
    commit_name: str
    pointer_sha256: str
    storage_identity_sha256: str
    disk: Mapping[str, Any]

    def as_receipt(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "backend_identity": VPS_BACKEND_IDENTITY,
            "backend_version": VPS_BACKEND_VERSION,
            "object_identity": self.event_id,
            "object_name": self.object_name,
            "object_sha256": self.object_sha256,
            "object_bytes": self.object_bytes,
            "commit_name": self.commit_name,
            "pointer_sha256": self.pointer_sha256,
            "event_id": self.event_id,
            "event_sha256": self.event_sha256,
            "storage_identity_sha256": self.storage_identity_sha256,
            "disk": dict(self.disk),
        }


class VpsD1Store:
    """Content-addressed immutable D1 store on the dedicated Ubuntu VPS."""

    def __init__(
        self,
        runner: VpsStoreRunner,
        *,
        storage_root: str,
        transport_identity: Mapping[str, Any] | None = None,
        min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
        danger_free_bytes: int = DEFAULT_DANGER_FREE_BYTES,
        expected_storage_identity_sha256: str | None = None,
    ):
        self.runner = runner
        self.storage_root = _normalize_remote_root(storage_root)
        self.transport_identity = dict(transport_identity or {})
        self.min_free_bytes = int(min_free_bytes)
        self.danger_free_bytes = int(danger_free_bytes)
        self.expected_storage_identity_sha256 = expected_storage_identity_sha256
        self._identity: dict[str, Any] | None = None

    @classmethod
    def from_env(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        runner: VpsStoreRunner | None = None,
        hop: VpsHop | None = None,
    ) -> "VpsD1Store":
        values = os.environ if environ is None else environ
        resolved = hop or hop_from_env(values)
        min_free = int(str(values.get("D1_VPS_MIN_FREE_BYTES") or DEFAULT_MIN_FREE_BYTES))
        danger_free = int(str(values.get("D1_VPS_DANGER_FREE_BYTES") or DEFAULT_DANGER_FREE_BYTES))
        return cls(
            runner or SshVpsRunner(resolved),
            storage_root=resolved.storage_root,
            transport_identity=resolved.transport_identity(),
            min_free_bytes=min_free,
            danger_free_bytes=danger_free,
        )

    # ------------------------------------------------------------------ wire
    def _call(
        self,
        command: Sequence[str],
        *,
        stdin: bytes | None = None,
        stdout: BinaryIO | None = None,
        allow_failure: bool = False,
    ) -> tuple[int, bytes, bytes]:
        exit_code, out, err = self.runner(command, stdin=stdin, stdout=stdout)
        if exit_code != 0 and not allow_failure:
            raise self._error(exit_code, err)
        return exit_code, out, err

    @staticmethod
    def _error(exit_code: int, stderr: bytes) -> VpsCommandError:
        detail: dict[str, Any] = {}
        reason = "D1_VPS_HELPER_FAILED"
        for line in reversed(bytes(stderr or b"").decode("utf-8", "replace").splitlines()):
            text = line.strip()
            if not text.startswith("{"):
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                detail = value
                reason = str(value.get("reason") or reason)
                break
        if reason == "D1_REMOTE_OBJECT_MISSING":
            return VpsObjectMissing(exit_code, reason, detail=detail)
        return VpsCommandError(exit_code, reason, detail=detail)

    @staticmethod
    def _json(payload: bytes, *, source: str) -> dict[str, Any]:
        text = bytes(payload or b"").decode("utf-8", "replace").strip()
        if not text:
            raise D1IntegrityError(f"D1 VPS {source} returned no receipt")
        line = text.splitlines()[-1]
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise D1IntegrityError(f"D1 VPS {source} returned an unreadable receipt") from exc
        if not isinstance(value, dict):
            raise D1IntegrityError(f"D1 VPS {source} receipt must be a JSON object")
        return value

    @staticmethod
    def _require_backend(value: Mapping[str, Any], *, source: str) -> None:
        if value.get("backend_version") != VPS_BACKEND_VERSION:
            raise D1IntegrityError(f"D1 VPS {source} backend version mismatch")
        if value.get("helper_version") != VPS_HELPER_VERSION:
            raise D1IntegrityError(f"D1 VPS {source} helper version mismatch")

    # -------------------------------------------------------------- identity
    def identity(self, *, refresh: bool = False) -> dict[str, Any]:
        if self._identity is not None and not refresh:
            return self._identity
        _, out, _ = self._call(["identity"])
        value = self._json(out, source="identity")
        if value.get("backend_identity") != VPS_BACKEND_IDENTITY:
            raise D1IntegrityError("D1 VPS backend identity mismatch")
        if value.get("backend_version") != VPS_BACKEND_VERSION:
            raise D1IntegrityError("D1 VPS backend version mismatch")
        if value.get("helper_version") != VPS_HELPER_VERSION:
            raise D1IntegrityError("D1 VPS helper version mismatch")
        reported_root = _normalize_remote_root(str(value.get("storage_root") or ""))
        if reported_root != self.storage_root:
            raise D1IntegrityError(
                "D1_VPS_STORAGE_ROOT_MISMATCH:"
                f"configured={self.storage_root}:reported={reported_root}"
            )
        expected = storage_identity_sha256(reported_root)
        if value.get("storage_identity_sha256") != expected:
            raise D1IntegrityError("D1 VPS storage identity mismatch")
        if (
            self.expected_storage_identity_sha256 is not None
            and expected != self.expected_storage_identity_sha256
        ):
            raise D1IntegrityError("configured D1 VPS storage root differs from expected identity")
        self._identity = value
        return value

    @property
    def storage_identity(self) -> str:
        return str(self.identity()["storage_identity_sha256"])

    def status(self) -> dict[str, Any]:
        _, out, _ = self._call([
            "status",
            "--min-free-bytes", str(self.min_free_bytes),
            "--danger-free-bytes", str(self.danger_free_bytes),
        ])
        value = self._json(out, source="status")
        self._require_backend(value, source="status")
        if value.get("storage_identity_sha256") != self.storage_identity:
            raise D1IntegrityError("D1 VPS status storage identity mismatch")
        return value

    # ------------------------------------------------------------------ io
    @staticmethod
    def _object_name(digest: str) -> str:
        return f"objects/{digest}.json"

    @staticmethod
    def _pointer_name(market: str, session_date: str) -> str:
        return f"sessions/{str(market).upper()}/{session_date}.json"

    @staticmethod
    def _activation_name(market: str) -> str:
        normalized = str(market).upper()
        if normalized not in {"CN", "US"}:
            raise ValueError("market must be CN or US")
        return f"system/activation/{normalized}.json"

    def put_bytes(
        self,
        name: str,
        payload: bytes,
        *,
        role: str,
        market: str | None = None,
        session_date: str | None = None,
        protocol: str | None = None,
        derived_replace: bool = False,
    ) -> dict[str, Any]:
        self.identity()
        expected_sha256 = sha256(payload).hexdigest()
        command = [
            "put",
            "--name", name,
            "--sha256", expected_sha256,
            "--role", role,
            "--danger-free-bytes", str(self.danger_free_bytes),
        ]
        if market:
            command += ["--market", str(market).upper()]
        if session_date:
            command += ["--session", str(session_date)]
        if protocol:
            command += ["--protocol", str(protocol)]
        if derived_replace:
            command += ["--derived-replace"]
        _, out, _ = self._call(command, stdin=payload)
        value = self._json(out, source="put")
        self._require_backend(value, source="put")
        if value.get("name") != name:
            raise D1IntegrityError("D1 VPS put receipt path mismatch")
        if value.get("sha256") != expected_sha256:
            raise D1IntegrityError("D1 VPS put receipt hash mismatch")
        if int(value.get("size") or -1) != len(payload):
            raise D1IntegrityError("D1 VPS put receipt size mismatch")
        if value.get("storage_identity_sha256") != self.storage_identity:
            raise D1IntegrityError("D1 VPS put receipt storage identity mismatch")
        return value

    def read_bytes(
        self,
        name: str,
        *,
        expected_sha256: str | None = None,
        sink: BinaryIO | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        self.identity()
        command = ["read", "--name", name]
        if expected_sha256:
            command += ["--sha256", str(expected_sha256)]
        _, out, err = self._call(command, stdout=sink)
        receipt = self._json(err, source="read")
        self._require_backend(receipt, source="read")
        payload = b"" if sink is not None else out
        actual = str(receipt.get("sha256") or "")
        size = int(receipt.get("size") or 0)
        if sink is None and size != len(payload):
            raise D1IntegrityError("D1 VPS read-back size mismatch")
        if expected_sha256 and actual != str(expected_sha256):
            raise D1IntegrityError("D1 VPS read-back hash mismatch")
        if sink is None and sha256(payload).hexdigest() != actual:
            raise D1IntegrityError("D1 VPS read-back payload hash mismatch")
        return payload, receipt

    def stat_object(self, name: str) -> dict[str, Any]:
        _, out, _ = self._call(["stat", "--name", name])
        value = self._json(out, source="stat")
        self._require_backend(value, source="stat")
        return value

    def scan(self, prefix: str = "", *, with_hash: bool = False) -> list[dict[str, Any]]:
        command = ["scan", "--prefix", str(prefix)]
        if with_hash:
            command.append("--hash")
        _, out, _ = self._call(command)
        value = self._json(out, source="scan")
        self._require_backend(value, source="scan")
        if value.get("storage_identity_sha256") != self.storage_identity:
            raise D1IntegrityError("D1 VPS scan storage identity mismatch")
        return [dict(item) for item in (value.get("entries") or ())]

    def cat_many(self, prefix: str, *, max_bytes: int = CAT_MANY_MAX_BYTES) -> list[dict[str, Any]]:
        _, out, err = self._call([
            "cat-many", "--prefix", str(prefix), "--max-bytes", str(int(max_bytes)),
        ])
        receipt = self._json(err, source="cat-many")
        self._require_backend(receipt, source="cat-many")
        values: list[dict[str, Any]] = []
        for line in bytes(out or b"").decode("utf-8", "replace").splitlines():
            text = line.strip()
            if not text:
                continue
            item = json.loads(text)
            item["payload"] = base64.b64decode(str(item.get("payload_b64") or ""))
            if sha256(item["payload"]).hexdigest() != str(item.get("sha256") or ""):
                raise D1IntegrityError("D1 VPS cat-many hash mismatch")
            values.append(item)
        if int(receipt.get("count") or 0) != len(values):
            raise D1IntegrityError("D1 VPS cat-many count mismatch")
        return values

    # ------------------------------------------------------------- pointers
    @staticmethod
    def _pointer_from_bytes(payload: bytes, *, market: str, session_date: str) -> dict[str, Any]:
        try:
            pointer = json.loads(bytes(payload).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise D1IntegrityError("D1 VPS commit pointer is unreadable") from exc
        if not isinstance(pointer, dict):
            raise D1IntegrityError("D1 VPS commit pointer must be a JSON object")
        without_hash = dict(pointer)
        actual = without_hash.pop("commit_sha256", None)
        if actual != content_sha256(without_hash):
            raise D1IntegrityError("D1 VPS commit hash mismatch")
        if pointer.get("schema_version") != VPS_POINTER_SCHEMA_VERSION:
            raise D1IntegrityError("D1 VPS commit schema mismatch")
        if pointer.get("backend_identity") != VPS_BACKEND_IDENTITY:
            raise D1IntegrityError("D1 VPS pointer backend identity mismatch")
        if pointer.get("backend_version") != VPS_BACKEND_VERSION:
            raise D1IntegrityError("D1 VPS pointer backend version mismatch")
        if pointer.get("protocol_version") != PROTOCOL_VERSION:
            raise D1IntegrityError("D1 VPS pointer protocol mismatch")
        if pointer.get("market") != str(market).upper():
            raise D1IntegrityError("D1 VPS pointer market mismatch")
        if pointer.get("session_date") != str(session_date):
            raise D1IntegrityError("D1 VPS pointer session mismatch")
        object_name = str(pointer.get("object_name") or "")
        object_sha = str(pointer.get("object_sha256") or "")
        if len(object_sha) != 64 or object_name != f"objects/{object_sha}.json":
            raise D1IntegrityError(
                "D1 VPS pointer object path is outside the content-addressed layout"
            )
        if not pointer.get("event_id") or not pointer.get("event_sha256"):
            raise D1IntegrityError("D1 VPS pointer event identity is incomplete")
        return pointer

    def _read_pointer(self, market: str, session_date: str) -> tuple[dict[str, Any], dict[str, Any]]:
        name = self._pointer_name(market, session_date)
        payload, receipt = self.read_bytes(name)
        return self._pointer_from_bytes(payload, market=market, session_date=session_date), receipt

    # ------------------------------------------------------------ activation
    def load_activation_record(
        self,
        market: str,
        *,
        require_current_storage_identity: bool = True,
    ) -> dict[str, Any]:
        name = self._activation_name(market)
        payload, _ = self.read_bytes(name)
        try:
            record = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise D1IntegrityError("D1 VPS activation record is unreadable") from exc
        validate_activation_record(
            record,
            expected_backend_identity=VPS_BACKEND_IDENTITY,
            expected_backend_version=VPS_BACKEND_VERSION,
            expected_storage_identity_sha256=(
                self.storage_identity if require_current_storage_identity else None
            ),
        )
        return dict(record)

    def create_activation_record(
        self,
        *,
        market: str,
        activation_timestamp: str,
        code_sha: str,
        source_contract: Mapping[str, Any],
        observer_version: str,
    ) -> dict[str, Any]:
        """Create one immutable per-market activation record after validation."""

        validation = self.validate_durable_storage()
        if validation["status"] != "VERIFIED":
            raise D1IntegrityError("VPS_DURABLE_STORAGE_NOT_VERIFIED")
        record = build_activation_record(
            market=market,
            activation_timestamp=activation_timestamp,
            backend_identity=VPS_BACKEND_IDENTITY,
            backend_version=VPS_BACKEND_VERSION,
            storage_identity_sha256=self.storage_identity,
            code_sha=code_sha,
            source_contract=source_contract,
            observer_version=observer_version,
        )
        self.put_bytes(
            self._activation_name(market),
            canonical_bytes(record),
            role="ACTIVATION_RECORD",
            market=market,
            protocol=PROTOCOL_VERSION,
        )
        loaded = self.load_activation_record(market)
        if loaded.get("record_sha256") != record.get("record_sha256"):
            raise D1IntegrityError("D1 VPS activation record read-back mismatch")
        return record

    # ------------------------------------------------------------ commitment
    def _validate_formal_snapshot(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        validate_session_snapshot(snapshot)
        if not snapshot.get("prospective_eligible") or snapshot.get("capture_status") != "COMPLETE":
            raise D1IntegrityError("D1 formal VPS commit requires a complete natural session")
        source = snapshot.get("source_identity") or {}
        if source.get("source_contract_version") != D1_SOURCE_CONTRACT_VERSION:
            raise D1IntegrityError("D1_SOURCE_ACTIVATION_CONTRACT_PENDING")
        if not source.get("activation_record_sha256"):
            raise D1IntegrityError("D1 activation record binding is missing")
        components = snapshot.get("components") or {}
        for name in (
            "raw_source_snapshot",
            "normalized_prefix_snapshot",
            "decision_snapshot",
            "research_observation_report",
        ):
            payload = (components.get(name) or {}).get("payload") or {}
            if (
                payload.get("contract_version") != D1_SOURCE_CONTRACT_VERSION
                or payload.get("status") != "VERIFIED"
            ):
                raise D1IntegrityError(f"D1 source contract incomplete: {name}")
        report = components["research_observation_report"]["payload"] or {}
        if not report.get("observer_version") or not report.get("report_markdown"):
            raise D1IntegrityError("D1 observer/report contract incomplete")
        return dict(source)

    def commit(self, snapshot: Mapping[str, Any]) -> VpsCommitResult:
        source = self._validate_formal_snapshot(snapshot)
        market = str(snapshot["market"]).upper()
        session_text = str(snapshot["session_date"])
        try:
            activation = self.load_activation_record(market)
        except VpsObjectMissing as exc:
            raise D1IntegrityError("D1 activation record is missing") from exc
        if source.get("activation_record_sha256") != activation.get("record_sha256"):
            raise D1IntegrityError("snapshot activation record hash mismatch")
        if not session_is_in_activation_window(activation, session_text):
            raise D1IntegrityError("D1_PRE_ACTIVATION_OR_POST_WINDOW_SESSION_REJECTED")
        session_identity = source.get("session_identity")
        if not isinstance(session_identity, Mapping) or session_identity.get("trade_date") != session_text:
            raise D1IntegrityError("D1 exact session identity mismatch")
        if session_identity.get("exact_exchange_calendar") is not True:
            raise D1IntegrityError("D1 exact exchange calendar proof is required")

        payload = canonical_bytes(snapshot)
        object_sha256 = sha256(payload).hexdigest()
        object_name = self._object_name(object_sha256)
        object_receipt = self.put_bytes(
            object_name,
            payload,
            role="OBJECT",
            market=market,
            session_date=session_text,
            protocol=PROTOCOL_VERSION,
        )
        pointer = {
            "schema_version": VPS_POINTER_SCHEMA_VERSION,
            "backend_identity": VPS_BACKEND_IDENTITY,
            "backend_version": VPS_BACKEND_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "event_id": snapshot["event_id"],
            "event_sha256": snapshot["event_sha256"],
            "market": market,
            "session_date": session_text,
            "object_name": object_name,
            "object_sha256": object_sha256,
            "object_size": len(payload),
            "classification": str(snapshot["data_classification"]),
        }
        pointer["commit_sha256"] = content_sha256(pointer)
        pointer_bytes = canonical_bytes(pointer)
        pointer_receipt = self.put_bytes(
            self._pointer_name(market, session_text),
            pointer_bytes,
            role="SESSION_COMMIT",
            market=market,
            session_date=session_text,
            protocol=PROTOCOL_VERSION,
        )
        # Read the committed session back through its pointer before the
        # session may be reported as committed.
        loaded = self.load(market, session_text)
        if loaded.get("event_sha256") != snapshot["event_sha256"]:
            raise D1IntegrityError("D1 VPS read-back event identity mismatch")
        disk = self.status()
        return VpsCommitResult(
            status="COMMITTED" if pointer_receipt.get("status") == "CREATED" else "IDEMPOTENT_REPLAY",
            event_id=str(snapshot["event_id"]),
            event_sha256=str(snapshot["event_sha256"]),
            object_name=object_name,
            object_sha256=object_sha256,
            object_bytes=int(object_receipt.get("size") or 0),
            commit_name=self._pointer_name(market, session_text),
            pointer_sha256=sha256(pointer_bytes).hexdigest(),
            storage_identity_sha256=self.storage_identity,
            disk=disk,
        )

    def load(self, market: str, session_date: date | str) -> dict[str, Any]:
        normalized = str(market).upper()
        session_text = (
            session_date.isoformat() if isinstance(session_date, date) else str(session_date)
        )
        pointer, _ = self._read_pointer(normalized, session_text)
        object_name = str(pointer["object_name"])
        payload, _ = self.read_bytes(object_name, expected_sha256=str(pointer["object_sha256"]))
        recorded_size = int(pointer.get("object_size") or len(payload))
        if len(payload) != recorded_size:
            raise D1IntegrityError("D1 VPS object size mismatch")
        try:
            snapshot = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise D1IntegrityError("D1 VPS session object is unreadable") from exc
        validate_session_snapshot(snapshot)
        if snapshot.get("event_sha256") != pointer.get("event_sha256"):
            raise D1IntegrityError("D1 VPS commit/object hash mismatch")
        if snapshot.get("event_id") != pointer.get("event_id"):
            raise D1IntegrityError("D1 VPS commit/object event mismatch")
        return snapshot

    # --------------------------------------------------------------- verify
    def verify(self, *, full_objects: bool = False) -> dict[str, Any]:
        self.identity()
        entries = self.scan("", with_hash=full_objects)
        sizes = {str(item["name"]): int(item.get("size") or 0) for item in entries}
        object_hashes = {
            str(item["name"]): str(item.get("sha256") or "")
            for item in entries
            if full_objects and str(item["name"]).startswith("objects/")
        }
        errors: list[str] = []
        found: dict[str, set[str]] = {"CN": set(), "US": set()}
        referenced: set[str] = set()
        sessions: list[dict[str, Any]] = []
        for market in ("CN", "US"):
            pointers = self.cat_many(f"sessions/{market}/")
            for item in pointers:
                name = str(item.get("name") or "")
                session_text = Path(name).stem
                try:
                    session = date.fromisoformat(session_text)
                    pointer = self._pointer_from_bytes(
                        item["payload"], market=market, session_date=session_text
                    )
                    object_name = str(pointer["object_name"])
                    if object_name not in sizes:
                        raise D1IntegrityError("D1 VPS session object is missing")
                    expected_object_sha = str(pointer["object_sha256"])
                    if int(pointer.get("object_size") or -1) != sizes[object_name]:
                        raise D1IntegrityError("D1 VPS session object size mismatch")
                    if full_objects and object_hashes.get(object_name) != expected_object_sha:
                        raise D1IntegrityError("D1 VPS session object hash mismatch")
                    if session.isoformat() in found[market]:
                        raise D1IntegrityError("D1 VPS duplicate session commit")
                    found[market].add(session.isoformat())
                    referenced.add(object_name)
                    sessions.append({
                        "market": market,
                        "session_date": session.isoformat(),
                        "event_id": str(pointer["event_id"]),
                        "event_sha256": str(pointer["event_sha256"]),
                        "object_name": object_name,
                        "object_sha256": expected_object_sha,
                        "object_size": sizes[object_name],
                        "pointer_sha256": str(item.get("sha256") or ""),
                    })
                except Exception as exc:  # noqa: BLE001 - reported as an error entry
                    errors.append(f"INVALID_SESSION:{market}:{name}:{exc}")
        present_objects = {name for name in sizes if name.startswith("objects/")}
        unreferenced = sorted(present_objects - referenced)
        activations: list[dict[str, Any]] = []
        for market in ("CN", "US"):
            name = self._activation_name(market)
            if name not in sizes:
                continue
            try:
                record = self.load_activation_record(
                    market, require_current_storage_identity=False
                )
                activations.append({
                    "market": market,
                    "name": name,
                    "record_sha256": str(record.get("record_sha256") or ""),
                    "code_sha": str(record.get("code_sha") or ""),
                    "first_eligible_full_exchange_session": str(
                        record.get("first_eligible_full_exchange_session") or ""
                    ),
                    "end_boundary_local_date": str(record.get("end_boundary_local_date") or ""),
                    "storage_identity_sha256": str(record.get("storage_identity_sha256") or ""),
                    "storage_identity_matches_current": (
                        record.get("storage_identity_sha256") == self.storage_identity
                    ),
                })
            except Exception as exc:  # noqa: BLE001
                errors.append(f"INVALID_ACTIVATION:{market}:{exc}")
        continuation_ready = all(item["storage_identity_matches_current"] for item in activations)
        return {
            "status": "VERIFIED" if not errors else "FAILED",
            "backend_identity": VPS_BACKEND_IDENTITY,
            "backend_version": VPS_BACKEND_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "storage_identity_sha256": self.storage_identity,
            "storage_root": self.storage_root,
            "full_object_hashes": bool(full_objects),
            "session_counts": {market: len(values) for market, values in found.items()},
            "sessions": sorted(sessions, key=lambda item: (item["market"], item["session_date"])),
            "missing_sessions": [],
            "errors": errors,
            "object_count": len(present_objects),
            "referenced_object_count": len(referenced),
            "referenced_object_bytes": sum(sizes[name] for name in sorted(referenced)),
            "unreferenced_objects": unreferenced,
            "activation_records": activations,
            "continuation_ready": continuation_ready,
        }

    # ------------------------------------------------------- export/recovery
    def _copy_graph_to(self, target: str | Path) -> dict[str, Any]:
        graph = self.verify()
        if graph["status"] != "VERIFIED":
            raise D1IntegrityError("source D1 VPS store failed verification")
        destination = Path(target)
        if destination.exists() and any(destination.iterdir()):
            raise D1IntegrityError("recovery target must be empty")
        destination.mkdir(parents=True, exist_ok=True)
        filesystem = FilesystemD1Store(destination)
        for market in ("CN", "US"):
            for session_text in sorted(
                item["session_date"] for item in graph["sessions"] if item["market"] == market
            ):
                filesystem.commit(self.load(market, session_text))
        recovered = filesystem.verify()
        if (
            recovered["status"] != "VERIFIED"
            or recovered["protocol_version"] != graph["protocol_version"]
            or recovered["session_counts"] != graph["session_counts"]
            or recovered["errors"] != []
        ):
            raise D1IntegrityError("D1 VPS recovery verification mismatch")
        return recovered

    def recover_to(self, target: str | Path) -> dict[str, Any]:
        return self._copy_graph_to(target)

    def export_to(self, target: str | Path) -> dict[str, Any]:
        """Write a verified local export of the whole store plus root manifest."""

        recovered = self._copy_graph_to(target)
        destination = Path(target)
        activation_dir = destination / "system" / "activation"
        for market in ("CN", "US"):
            name = self._activation_name(market)
            if not self.stat_object(name).get("exists"):
                continue
            payload, _ = self.read_bytes(name)
            activation_dir.mkdir(parents=True, exist_ok=True)
            (activation_dir / f"{market}.json").write_bytes(payload)
        manifest = self.build_manifest()
        manifest_path = destination / VPS_MANIFEST_NAME
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(canonical_bytes(manifest))
        return {
            **recovered,
            "manifest": manifest,
            "manifest_path": str(manifest_path),
            "exported_root": str(destination),
        }

    def build_manifest(self, *, graph: Mapping[str, Any] | None = None) -> dict[str, Any]:
        value = dict(graph or self.verify())
        if value.get("status") != "VERIFIED":
            raise D1IntegrityError("D1 VPS store manifest requires a verified store")
        manifest = {
            "schema_version": VPS_MANIFEST_SCHEMA_VERSION,
            "backend_identity": VPS_BACKEND_IDENTITY,
            "backend_version": VPS_BACKEND_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "storage_identity_sha256": self.storage_identity,
            "storage_root": self.storage_root,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "activation_records": list(value.get("activation_records") or ()),
            "session_counts": dict(value.get("session_counts") or {}),
            "sessions": list(value.get("sessions") or ()),
            "referenced_object_count": int(value.get("referenced_object_count") or 0),
            "referenced_object_bytes": int(value.get("referenced_object_bytes") or 0),
            "unreferenced_objects": list(value.get("unreferenced_objects") or ()),
            "evidence_role": "DERIVED_INDEX_NOT_FORMAL_SESSION_EVIDENCE",
        }
        manifest["manifest_sha256"] = content_sha256(manifest)
        return manifest

    def publish_manifest(self) -> dict[str, Any]:
        manifest = self.build_manifest()
        receipt = self.put_bytes(
            VPS_MANIFEST_NAME,
            canonical_bytes(manifest),
            role="STORE_MANIFEST",
            protocol=PROTOCOL_VERSION,
            derived_replace=True,
        )
        return {"manifest": manifest, "receipt": receipt}

    def migrate_from(self, source: str | Path) -> dict[str, Any]:
        """Import a verified local export into this (empty) D1 store."""

        source_path = Path(source)
        if not source_path.is_dir() or not (source_path / "sessions").is_dir():
            raise D1IntegrityError("migration source export is missing or incomplete")
        filesystem = FilesystemD1Store(source_path)
        source_verify = filesystem.verify()
        if source_verify["status"] != "VERIFIED" or source_verify["errors"]:
            raise D1IntegrityError("migration source export failed verification")
        graph_before = self.verify()
        if graph_before["session_counts"] != {"CN": 0, "US": 0}:
            raise D1IntegrityError("migration target must be an empty formal D1 store")
        for market in ("CN", "US"):
            path = source_path / "system" / "activation" / f"{market}.json"
            if not path.exists():
                continue
            payload = path.read_bytes()
            record = json.loads(payload.decode("utf-8"))
            validate_activation_record(
                record,
                expected_backend_identity=VPS_BACKEND_IDENTITY,
                expected_backend_version=VPS_BACKEND_VERSION,
            )
            if record.get("storage_identity_sha256") != self.storage_identity:
                raise D1IntegrityError(
                    "D1_VPS_MIGRATION_STORAGE_IDENTITY_MISMATCH_ACTIVATION_REQUIRES_DECISION"
                )
            self.put_bytes(
                self._activation_name(market),
                payload,
                role="ACTIVATION_RECORD",
                market=market,
                protocol=PROTOCOL_VERSION,
            )
        imported = 0
        for market in ("CN", "US"):
            directory = source_path / "sessions" / market
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.json")):
                snapshot = filesystem.load(market, date.fromisoformat(path.stem))
                self.commit(snapshot)
                imported += 1
        graph_after = self.verify()
        if (
            graph_after["status"] != "VERIFIED"
            or graph_after["session_counts"] != source_verify["session_counts"]
            or graph_after["errors"] != []
        ):
            raise D1IntegrityError("D1 VPS migration verification mismatch")
        return {
            "status": "MIGRATED_AND_VERIFIED",
            "imported_sessions": imported,
            "session_counts": graph_after["session_counts"],
            "source_counts": source_verify["session_counts"],
            "activation_records": graph_after["activation_records"],
            "storage_identity_sha256": self.storage_identity,
        }

    # ------------------------------------------------------------ validation
    def validate_durable_storage(
        self, *, expected_storage_identity_sha256: str | None = None
    ) -> dict[str, Any]:
        """Exercise the real VPS with a synthetic object and independent recovery."""

        if (
            expected_storage_identity_sha256 is not None
            and self.storage_identity != expected_storage_identity_sha256
        ):
            raise D1IntegrityError("configured D1 VPS storage differs from expected identity")
        frozen = verify_frozen_protocol()
        identity = self.identity()
        graph = self.verify()
        if graph["session_counts"] != {"CN": 0, "US": 0}:
            raise D1IntegrityError("synthetic validation requires an empty formal D1 session graph")
        status = self.status()
        payload = canonical_bytes({
            "classification": SYNTHETIC_CLASSIFICATION,
            "backend_identity": VPS_BACKEND_IDENTITY,
            "backend_version": VPS_BACKEND_VERSION,
            "protocol_version": PROTOCOL_VERSION,
        })
        digest = sha256(payload).hexdigest()
        name = "system/validation/vps-durable-validation-v1.json"
        created = self.put_bytes(name, payload, role="VALIDATION_ONLY", protocol=PROTOCOL_VERSION)
        replay = self.put_bytes(name, payload, role="VALIDATION_ONLY", protocol=PROTOCOL_VERSION)
        conflict_payload = payload + b" "
        exit_code, _, err = self._call(
            [
                "put",
                "--name", name,
                "--sha256", sha256(conflict_payload).hexdigest(),
                "--role", "VALIDATION_ONLY",
                "--danger-free-bytes", str(self.danger_free_bytes),
            ],
            stdin=conflict_payload,
            allow_failure=True,
        )
        if exit_code == HELPER_EXIT_CONFLICT:
            conflict_failed_closed = True
        elif exit_code == 0:
            raise D1IntegrityError("D1 VPS create-only identity accepted different bytes")
        else:
            raise self._error(exit_code, err)
        with tempfile.TemporaryDirectory() as directory:
            recovered = Path(directory) / "validation-object.json"
            with recovered.open("wb") as sink:
                self.read_bytes(name, expected_sha256=digest, sink=sink)
            if sha256(recovered.read_bytes()).hexdigest() != digest:
                raise D1IntegrityError("clean-directory validation recovery hash mismatch")
        after = self.verify()
        if after["session_counts"] != {"CN": 0, "US": 0}:
            raise D1IntegrityError("D1 VPS formal session graph changed during synthetic validation")
        return {
            "status": "VERIFIED",
            "classification": SYNTHETIC_CLASSIFICATION,
            "backend_identity": VPS_BACKEND_IDENTITY,
            "backend_version": VPS_BACKEND_VERSION,
            "helper_version": VPS_HELPER_VERSION,
            "storage_root": self.storage_root,
            "storage_identity_sha256": self.storage_identity,
            "transport_identity": dict(self.transport_identity),
            "ssh_authentication": "PUBLIC_KEY_ONLY_HOST_KEY_PINNED",
            "remote_python_version": str(identity.get("python_version") or ""),
            "object_name": name,
            "object_sha256": digest,
            "create_status": str(created.get("status")),
            "replay_status": str(replay.get("status")),
            "read_back_hash_match": True,
            "idempotent_rerun": replay.get("status") == "IDEMPOTENT_REPLAY",
            "clean_directory_recovery": True,
            "different_content_fail_closed": conflict_failed_closed,
            "disk": {
                "total_bytes": int(status.get("total_bytes") or 0),
                "used_bytes": int(status.get("used_bytes") or 0),
                "free_bytes": int(status.get("free_bytes") or 0),
                "store_bytes": int(status.get("store_bytes") or 0),
                "object_count": int(status.get("object_count") or 0),
                "session_count": int(
                    sum(int(value) for value in (status.get("session_counts") or {}).values())
                ),
                "space_status": str(status.get("space_status") or ""),
            },
            "session_counts": after["session_counts"],
            **frozen,
        }


__all__ = [
    "DEFAULT_DANGER_FREE_BYTES",
    "DEFAULT_MIN_FREE_BYTES",
    "DEFAULT_VPS_HELPER_PATH",
    "DEFAULT_VPS_STORAGE_ROOT",
    "SshVpsRunner",
    "SYNTHETIC_CLASSIFICATION",
    "VPS_BACKEND_IDENTITY",
    "VPS_BACKEND_VERSION",
    "VPS_HELPER_VERSION",
    "VPS_MANIFEST_NAME",
    "VpsCommandError",
    "VpsCommitResult",
    "VpsD1Store",
    "VpsHop",
    "VpsObjectMissing",
    "fingerprint_from_public_key",
    "hop_from_env",
    "known_hosts_fingerprints",
    "storage_identity_sha256",
]
