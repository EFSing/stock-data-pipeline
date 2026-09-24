"""Google Drive durable backend for SETUP_01 D1 prospective snapshots.

Only the configured research folder is addressed.  The service account is not
allowed to discover My Drive, production Sheets, holdings, or unrelated files.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol
from uuid import uuid4

from research.setup01_d1_prospective import (
    D1IntegrityError,
    FilesystemD1Store,
    PROTOCOL_VERSION,
    canonical_bytes,
    content_sha256,
    validate_session_snapshot,
)


DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
JSON_MIME = "application/json"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"


class D1DriveApi(Protocol):
    def metadata(self, file_id: str) -> Mapping[str, Any]: ...
    def list_children(self, parent_id: str, *, name: str | None = None) -> list[Mapping[str, Any]]: ...
    def create_folder(self, parent_id: str, name: str) -> Mapping[str, Any]: ...
    def create_file(
        self, parent_id: str, name: str, payload: bytes, *, app_properties: Mapping[str, str]
    ) -> Mapping[str, Any]: ...
    def download(self, file_id: str) -> bytes: ...


class GoogleDriveApi:
    """Small Drive v3 client using the already-required google-auth package."""

    API_ROOT = "https://www.googleapis.com/drive/v3"
    UPLOAD_ROOT = "https://www.googleapis.com/upload/drive/v3"

    def __init__(self, session: Any):
        self.session = session

    @classmethod
    def from_service_account_env(cls) -> "GoogleDriveApi":
        raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if not raw:
            raise RuntimeError("缺少 GOOGLE_SERVICE_ACCOUNT_JSON")
        try:
            info = json.loads(raw)
        except json.JSONDecodeError:
            info = json.loads(base64.b64decode(raw).decode("utf-8"))
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2.service_account import Credentials

        credentials = Credentials.from_service_account_info(info, scopes=[DRIVE_SCOPE])
        return cls(AuthorizedSession(credentials))

    @staticmethod
    def service_account_email_from_env() -> str:
        raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if not raw:
            raise RuntimeError("缺少 GOOGLE_SERVICE_ACCOUNT_JSON")
        try:
            info = json.loads(raw)
        except json.JSONDecodeError:
            info = json.loads(base64.b64decode(raw).decode("utf-8"))
        email = str(info.get("client_email") or "").strip()
        if not email:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON 缺少 client_email")
        return email

    @staticmethod
    def _checked(response: Any) -> Any:
        response.raise_for_status()
        return response

    def metadata(self, file_id: str) -> Mapping[str, Any]:
        response = self._checked(self.session.get(
            f"{self.API_ROOT}/files/{file_id}",
            params={
                "fields": "id,name,mimeType,trashed,capabilities(canAddChildren,canDownload)",
                "supportsAllDrives": "true",
            },
        ))
        return response.json()

    def list_children(self, parent_id: str, *, name: str | None = None) -> list[Mapping[str, Any]]:
        escaped_parent = parent_id.replace("'", "\\'")
        query = f"'{escaped_parent}' in parents and trashed = false"
        if name is not None:
            query += " and name = '" + name.replace("'", "\\'") + "'"
        files: list[Mapping[str, Any]] = []
        page_token: str | None = None
        while True:
            params = {
                "q": query,
                "fields": "nextPageToken,files(id,name,mimeType,size,appProperties)",
                "pageSize": 1000,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if page_token:
                params["pageToken"] = page_token
            response = self._checked(self.session.get(f"{self.API_ROOT}/files", params=params))
            value = response.json()
            files.extend(value.get("files") or ())
            page_token = value.get("nextPageToken")
            if not page_token:
                return files

    def create_folder(self, parent_id: str, name: str) -> Mapping[str, Any]:
        response = self._checked(self.session.post(
            f"{self.API_ROOT}/files",
            params={"fields": "id,name,mimeType", "supportsAllDrives": "true"},
            json={"name": name, "mimeType": DRIVE_FOLDER_MIME, "parents": [parent_id]},
        ))
        return response.json()

    def create_file(
        self, parent_id: str, name: str, payload: bytes, *, app_properties: Mapping[str, str]
    ) -> Mapping[str, Any]:
        boundary = f"d1-{uuid4().hex}"
        metadata = canonical_bytes({
            "name": name,
            "mimeType": JSON_MIME,
            "parents": [parent_id],
            "appProperties": dict(app_properties),
        }).rstrip(b"\n")
        body = b"".join((
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode(),
            metadata,
            f"\r\n--{boundary}\r\nContent-Type: {JSON_MIME}\r\n\r\n".encode(),
            payload,
            f"\r\n--{boundary}--\r\n".encode(),
        ))
        response = self._checked(self.session.post(
            f"{self.UPLOAD_ROOT}/files",
            params={"uploadType": "multipart", "fields": "id,name,mimeType,size", "supportsAllDrives": "true"},
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
            data=body,
        ))
        return response.json()

    def download(self, file_id: str) -> bytes:
        response = self._checked(self.session.get(
            f"{self.API_ROOT}/files/{file_id}",
            params={"alt": "media", "supportsAllDrives": "true"},
        ))
        return bytes(response.content)


@dataclass(frozen=True)
class DriveCommitResult:
    status: str
    event_id: str
    event_sha256: str
    object_file_id: str
    commit_file_id: str


class GoogleDriveD1Store:
    """Content-addressed immutable D1 store below one configured Drive folder."""

    def __init__(self, api: D1DriveApi, folder_id: str):
        if not str(folder_id).strip():
            raise ValueError("D1 research folder id is required")
        self.api = api
        self.folder_id = str(folder_id).strip()

    @classmethod
    def from_env(cls) -> "GoogleDriveD1Store":
        folder_id = os.environ.get("D1_RESEARCH_DRIVE_FOLDER_ID", "").strip()
        if not folder_id:
            raise RuntimeError("缺少 D1_RESEARCH_DRIVE_FOLDER_ID")
        return cls(GoogleDriveApi.from_service_account_env(), folder_id)

    def _unique_child(self, parent_id: str, name: str) -> Mapping[str, Any] | None:
        matches = self.api.list_children(parent_id, name=name)
        if len(matches) > 1:
            raise D1IntegrityError(f"duplicate immutable Drive name: {name}")
        return matches[0] if matches else None

    def _ensure_folder(self, parent_id: str, name: str) -> str:
        existing = self._unique_child(parent_id, name)
        if existing is not None:
            if existing.get("mimeType") != DRIVE_FOLDER_MIME:
                raise D1IntegrityError(f"Drive path is not a folder: {name}")
            return str(existing["id"])
        created = self.api.create_folder(parent_id, name)
        if created.get("mimeType") != DRIVE_FOLDER_MIME:
            raise D1IntegrityError(f"Drive folder create failed: {name}")
        return str(created["id"])

    def _layout(self) -> dict[str, str]:
        objects = self._ensure_folder(self.folder_id, "objects")
        sessions = self._ensure_folder(self.folder_id, "sessions")
        return {
            "objects": objects,
            "sessions": sessions,
            "CN": self._ensure_folder(sessions, "CN"),
            "US": self._ensure_folder(sessions, "US"),
            "system": self._ensure_folder(self.folder_id, "system"),
        }

    def _write_once(
        self, parent_id: str, name: str, payload: bytes, *, app_properties: Mapping[str, str]
    ) -> tuple[str, bool]:
        existing = self._unique_child(parent_id, name)
        if existing is not None:
            if existing.get("mimeType") != JSON_MIME or self.api.download(str(existing["id"])) != payload:
                raise D1IntegrityError(f"immutable Drive object mismatch: {name}")
            return str(existing["id"]), False
        created = self.api.create_file(parent_id, name, payload, app_properties=app_properties)
        file_id = str(created.get("id") or "")
        if not file_id or self.api.download(file_id) != payload:
            raise D1IntegrityError(f"Drive read-back mismatch: {name}")
        return file_id, True

    def verify_access(self, *, write_probe: bool = False) -> dict[str, Any]:
        metadata = self.api.metadata(self.folder_id)
        capabilities = metadata.get("capabilities") or {}
        if metadata.get("mimeType") != DRIVE_FOLDER_MIME or metadata.get("trashed"):
            raise D1IntegrityError("configured Drive identity is not an active folder")
        if capabilities.get("canAddChildren") is not True:
            raise D1IntegrityError("service account lacks writer access to D1 folder")
        result = {
            "status": "ACCESS_VERIFIED",
            "folder_id": self.folder_id,
            "scope_boundary": "CONFIGURED_FOLDER_ONLY",
            "minimum_permission": "writer",
            "write_readback_probe": False,
        }
        if write_probe:
            system = self._layout()["system"]
            payload = canonical_bytes({
                "protocol_version": PROTOCOL_VERSION,
                "purpose": "D1_DURABLE_STORAGE_WRITE_READBACK_PROBE_V1",
                "data_classification": "PUBLIC_MARKET_RESEARCH_ONLY_NO_HOLDINGS",
            })
            _, created = self._write_once(
                system,
                "write-readback-probe-v1.json",
                payload,
                app_properties={"d1_kind": "ACCESS_PROBE", "sha256": content_sha256(json.loads(payload))},
            )
            result["write_readback_probe"] = True
            result["probe_status"] = "CREATED_AND_VERIFIED" if created else "IDEMPOTENT_AND_VERIFIED"
        return result

    def commit(self, snapshot: Mapping[str, Any]) -> DriveCommitResult:
        validate_session_snapshot(snapshot)
        layout = self._layout()
        digest = str(snapshot["event_sha256"])
        object_name = f"{digest}.json"
        object_id, _ = self._write_once(
            layout["objects"],
            object_name,
            canonical_bytes(snapshot),
            app_properties={"d1_kind": "OBJECT", "sha256": digest, "protocol": PROTOCOL_VERSION},
        )
        pointer = {
            "schema_version": "setup01-d1-session-commit-v1",
            "protocol_version": PROTOCOL_VERSION,
            "event_id": snapshot["event_id"],
            "event_sha256": digest,
            "market": snapshot["market"],
            "session_date": snapshot["session_date"],
            "object_relative_path": f"objects/{object_name}",
            "drive_object_file_id": object_id,
        }
        pointer["commit_sha256"] = content_sha256(pointer)
        commit_id, created = self._write_once(
            layout[str(snapshot["market"])],
            f"{snapshot['session_date']}.json",
            canonical_bytes(pointer),
            app_properties={
                "d1_kind": "SESSION_COMMIT",
                "market": str(snapshot["market"]),
                "session_date": str(snapshot["session_date"]),
                "sha256": digest,
            },
        )
        return DriveCommitResult(
            "COMMITTED" if created else "IDEMPOTENT_REPLAY",
            str(snapshot["event_id"]),
            digest,
            object_id,
            commit_id,
        )

    def _load_pointer(self, market: str, session_date: date) -> dict[str, Any]:
        layout = self._layout()
        item = self._unique_child(layout[market.upper()], f"{session_date.isoformat()}.json")
        if item is None:
            raise FileNotFoundError(f"missing D1 session: {market}:{session_date.isoformat()}")
        pointer = json.loads(self.api.download(str(item["id"])))
        without_hash = dict(pointer)
        actual = without_hash.pop("commit_sha256", None)
        if actual != content_sha256(without_hash):
            raise D1IntegrityError("Drive commit hash mismatch")
        return pointer

    def load(self, market: str, session_date: date) -> dict[str, Any]:
        pointer = self._load_pointer(market, session_date)
        snapshot = json.loads(self.api.download(str(pointer["drive_object_file_id"])))
        validate_session_snapshot(snapshot)
        if snapshot["event_sha256"] != pointer["event_sha256"]:
            raise D1IntegrityError("Drive commit/object hash mismatch")
        return snapshot

    def verify(self, expected_sessions: Mapping[str, Iterable[date]] | None = None) -> dict[str, Any]:
        layout = self._layout()
        found: dict[str, set[str]] = {"CN": set(), "US": set()}
        errors: list[str] = []
        for market in ("CN", "US"):
            for item in self.api.list_children(layout[market]):
                name = str(item.get("name") or "")
                try:
                    session = date.fromisoformat(name.removesuffix(".json"))
                    self.load(market, session)
                    if session.isoformat() in found[market]:
                        errors.append(f"DUPLICATE_SESSION:{market}:{session.isoformat()}")
                    found[market].add(session.isoformat())
                except Exception as exc:
                    errors.append(f"INVALID_SESSION:{market}:{name}:{exc}")
        missing: list[str] = []
        if expected_sessions:
            for market, sessions in expected_sessions.items():
                for session in sessions:
                    if session.isoformat() not in found.get(market.upper(), set()):
                        missing.append(f"{market.upper()}:{session.isoformat()}")
        return {
            "status": "VERIFIED" if not errors and not missing else "FAILED",
            "protocol_version": PROTOCOL_VERSION,
            "session_counts": {market: len(values) for market, values in found.items()},
            "missing_sessions": missing,
            "errors": errors,
        }

    def recover_to(self, target: str | Path) -> dict[str, Any]:
        source_check = self.verify()
        if source_check["status"] != "VERIFIED":
            raise D1IntegrityError("source Drive store failed verification")
        destination = Path(target)
        if destination.exists() and any(destination.iterdir()):
            raise D1IntegrityError("recovery target must be empty")
        for market in ("CN", "US"):
            for session_text in sorted(self._session_names(market)):
                snapshot = self.load(market, date.fromisoformat(session_text))
                FilesystemD1Store(destination).commit(snapshot)
        recovered = FilesystemD1Store(destination).verify()
        if recovered != source_check:
            raise D1IntegrityError("Drive recovery verification mismatch")
        return recovered

    def _session_names(self, market: str) -> set[str]:
        folder = self._layout()[market.upper()]
        return {
            str(item.get("name") or "").removesuffix(".json")
            for item in self.api.list_children(folder)
            if str(item.get("name") or "").endswith(".json")
        }


__all__ = [
    "D1DriveApi",
    "DRIVE_SCOPE",
    "DriveCommitResult",
    "GoogleDriveApi",
    "GoogleDriveD1Store",
]
