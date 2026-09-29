"""Google Cloud Storage durable backend for SETUP_01 D1.

The adapter uses the GCS JSON API directly through ``google-auth``.  That
keeps the runtime dependency small while allowing the immutable write contract
to use the native ``ifGenerationMatch=0`` precondition.  Bucket administration
is intentionally outside this runtime adapter.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from typing import Any, Iterable, Mapping, Protocol
from urllib.parse import quote
from uuid import uuid4

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


GCS_BACKEND_IDENTITY = "SETUP01_D1_GCS_DURABLE_STORAGE"
GCS_BACKEND_VERSION = "GCS_D1_DURABLE_BACKEND_V1"
APPROVAL_ENV = "D1_GCS_BACKEND_APPROVED_FOR_FORMAL_D1"
GCS_SCOPE = "https://www.googleapis.com/auth/devstorage.read_write"
JSON_MIME = "application/json"
GCS_META_BACKEND = "d1_backend_identity"
GCS_META_BACKEND_VERSION = "d1_backend_version"
GCS_META_KIND = "d1_kind"
GCS_META_PROTOCOL = "d1_protocol_version"
GCS_META_SHA256 = "d1_sha256"
GCS_META_CLASSIFICATION = "d1_classification"
GCS_META_MARKET = "d1_market"
GCS_META_SESSION = "d1_session_date"


class GcsApiError(RuntimeError):
    """A bounded GCS API failure with its HTTP status preserved."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = int(status_code)


class GcsNotFound(GcsApiError):
    pass


class GcsPreconditionFailed(GcsApiError):
    pass


def require_approved_formal_backend() -> None:
    """Keep GCS a retained adapter instead of a second writable D1 backend.

    The approved D1 durable backend is the dedicated Ubuntu VPS.  Any GCS
    formal write or activation must be explicitly re-approved first, so two
    backends can never hold writable formal D1 authority at the same time.
    """

    if str(os.environ.get(APPROVAL_ENV, "")).strip().lower() not in {"1", "true", "yes"}:
        raise D1IntegrityError(
            "D1_BACKEND_NOT_APPROVED:SETUP01_D1_VPS_SSH_DURABLE_STORAGE is the current formal "
            "D1 durable backend; set " + APPROVAL_ENV + "=true only after a recorded decision"
        )


@dataclass(frozen=True)
class GcsObject:
    name: str
    generation: str
    metadata: Mapping[str, str]
    payload: bytes


class D1GcsApi(Protocol):
    def bucket_metadata(self, bucket: str) -> Mapping[str, Any]: ...

    def create_object(
        self,
        bucket: str,
        name: str,
        payload: bytes,
        *,
        metadata: Mapping[str, str],
    ) -> GcsObject: ...

    def get_object(self, bucket: str, name: str) -> GcsObject: ...

    def list_objects(self, bucket: str, *, prefix: str) -> list[Mapping[str, Any]]: ...


def _credential_info_from_env() -> dict[str, Any]:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise RuntimeError("缺少 GOOGLE_SERVICE_ACCOUNT_JSON")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = json.loads(base64.b64decode(raw).decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON 必须是 JSON object")
    return value


class GoogleCloudStorageApi:
    """Small authenticated client for the bounded GCS JSON API surface."""

    API_ROOT = "https://storage.googleapis.com/storage/v1"
    UPLOAD_ROOT = "https://storage.googleapis.com/upload/storage/v1"

    def __init__(self, session: Any):
        self.session = session

    @classmethod
    def from_service_account_env(cls) -> "GoogleCloudStorageApi":
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2.service_account import Credentials

        credentials = Credentials.from_service_account_info(
            _credential_info_from_env(), scopes=[GCS_SCOPE]
        )
        return cls(AuthorizedSession(credentials))

    @staticmethod
    def service_account_email_from_env() -> str:
        email = str(_credential_info_from_env().get("client_email") or "").strip()
        if not email:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON 缺少 client_email")
        return email

    @staticmethod
    def project_id_from_env() -> str | None:
        value = str(_credential_info_from_env().get("project_id") or "").strip()
        return value or None

    @staticmethod
    def _raise(response: Any) -> Any:
        status = int(getattr(response, "status_code", 0) or 0)
        if status == 404:
            raise GcsNotFound(status, "GCS object or bucket not found")
        if status in {409, 412}:
            raise GcsPreconditionFailed(status, "GCS create-only precondition failed")
        response.raise_for_status()
        return response

    def bucket_metadata(self, bucket: str) -> Mapping[str, Any]:
        response = self._raise(self.session.get(
            f"{self.API_ROOT}/b/{quote(bucket, safe='')}",
            params={
                "fields": (
                    "id,name,location,storageClass,iamConfiguration,versioning,"
                    "retentionPolicy,projectNumber,timeCreated,updated"
                )
            },
        ))
        return response.json()

    def create_object(
        self,
        bucket: str,
        name: str,
        payload: bytes,
        *,
        metadata: Mapping[str, str],
    ) -> GcsObject:
        boundary = f"d1-gcs-{uuid4().hex}"
        object_metadata = {
            "name": name,
            "contentType": JSON_MIME,
            "metadata": {str(key): str(value) for key, value in metadata.items()},
        }
        body = b"".join((
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode("utf-8"),
            json.dumps(object_metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            f"\r\n--{boundary}\r\nContent-Type: {JSON_MIME}\r\n\r\n".encode("utf-8"),
            payload,
            f"\r\n--{boundary}--\r\n".encode("utf-8"),
        ))
        response = self._raise(self.session.post(
            f"{self.UPLOAD_ROOT}/b/{quote(bucket, safe='')}/o",
            params={
                "uploadType": "multipart",
                "ifGenerationMatch": "0",
                "fields": "name,generation,metadata",
            },
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
            data=body,
        ))
        value = response.json()
        return GcsObject(
            name=str(value.get("name") or name),
            generation=str(value.get("generation") or ""),
            metadata={str(key): str(item) for key, item in (value.get("metadata") or {}).items()},
            payload=bytes(payload),
        )

    def get_object(self, bucket: str, name: str) -> GcsObject:
        metadata_response = self._raise(self.session.get(
            f"{self.API_ROOT}/b/{quote(bucket, safe='')}/o/{quote(name, safe='')}",
            params={
                "fields": "name,generation,metadata,contentType,size,md5Hash",
            },
        ))
        metadata_value = metadata_response.json()
        media_response = self._raise(self.session.get(
            f"{self.API_ROOT}/b/{quote(bucket, safe='')}/o/{quote(name, safe='')}",
            params={"alt": "media"},
        ))
        return GcsObject(
            name=str(metadata_value.get("name") or name),
            generation=str(metadata_value.get("generation") or ""),
            metadata={
                str(key): str(value)
                for key, value in (metadata_value.get("metadata") or {}).items()
            },
            payload=bytes(media_response.content),
        )

    def list_objects(self, bucket: str, *, prefix: str) -> list[Mapping[str, Any]]:
        values: list[Mapping[str, Any]] = []
        page_token: str | None = None
        while True:
            params = {
                "prefix": prefix,
                "maxResults": "1000",
                "fields": "nextPageToken,items(name,generation,metadata)",
            }
            if page_token:
                params["pageToken"] = page_token
            response = self._raise(self.session.get(
                f"{self.API_ROOT}/b/{quote(bucket, safe='')}/o", params=params
            ))
            value = response.json()
            values.extend(value.get("items") or ())
            page_token = value.get("nextPageToken")
            if not page_token:
                return values


def bucket_identity_sha256(bucket: str, project: str | None = None) -> str:
    identity = f"gs://{str(project or '').strip()}/{str(bucket).strip()}"
    return sha256(identity.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GcsCommitResult:
    status: str
    event_id: str
    event_sha256: str
    object_name: str
    object_generation: str
    commit_name: str
    commit_generation: str


class GoogleCloudStorageD1Store:
    """Content-addressed immutable D1 store in one dedicated GCS bucket."""

    def __init__(self, api: D1GcsApi, bucket: str, *, project: str | None = None):
        if not str(bucket).strip():
            raise ValueError("D1 research GCS bucket is required")
        self.api = api
        self.bucket = str(bucket).strip()
        self.project = str(project or "").strip() or None

    @classmethod
    def from_env(cls) -> "GoogleCloudStorageD1Store":
        bucket = os.environ.get("D1_RESEARCH_GCS_BUCKET", "").strip()
        if not bucket:
            raise RuntimeError("缺少 D1_RESEARCH_GCS_BUCKET")
        project = os.environ.get("D1_RESEARCH_GCS_PROJECT", "").strip() or None
        api = GoogleCloudStorageApi.from_service_account_env()
        # A cross-project bucket must be explicit.  Otherwise the service
        # account project is the safest available identity for the hash.
        project = project or api.project_id_from_env()
        return cls(api, bucket, project=project)

    @property
    def bucket_identity_sha256(self) -> str:
        return bucket_identity_sha256(self.bucket, self.project)

    def _bucket_policy(self) -> dict[str, Any]:
        value = dict(self.api.bucket_metadata(self.bucket))
        if value.get("name") != self.bucket:
            raise D1IntegrityError("GCS bucket identity mismatch")
        if str(value.get("storageClass") or "").upper() != "STANDARD":
            raise D1IntegrityError("D1 GCS bucket must use STANDARD storage")
        iam = value.get("iamConfiguration") or {}
        uniform = iam.get("uniformBucketLevelAccess") or {}
        if uniform.get("enabled") is not True:
            raise D1IntegrityError("D1 GCS bucket requires uniform bucket-level access")
        public_prevention = iam.get("publicAccessPrevention", value.get("publicAccessPrevention"))
        if str(public_prevention or "").lower() != "enforced":
            raise D1IntegrityError("D1 GCS bucket requires Public Access Prevention enforced")
        if (value.get("versioning") or {}).get("enabled") is True:
            raise D1IntegrityError("D1 GCS object versioning must remain disabled in this phase")
        retention = value.get("retentionPolicy")
        if retention and (retention.get("isLocked") or retention.get("retentionPeriod")):
            raise D1IntegrityError("GCS_BUCKET_RETENTION_POLICY_REQUIRES_REVIEW")
        return value

    def verify_access(self, *, write_probe: bool = False) -> dict[str, Any]:
        policy = self._bucket_policy()
        result = {
            "status": "ACCESS_VERIFIED",
            "backend_identity": GCS_BACKEND_IDENTITY,
            "backend_version": GCS_BACKEND_VERSION,
            "bucket": self.bucket,
            "project": self.project,
            "bucket_identity_sha256": self.bucket_identity_sha256,
            "scope_boundary": "DEDICATED_BUCKET_ONLY",
            "required_runtime_permissions": [
                "storage.objects.create",
                "storage.objects.get",
                "storage.objects.list",
            ],
            "storage_validation_permissions": ["storage.buckets.get"],
            "write_readback_probe": False,
            "bucket_location": policy.get("location"),
            "storage_class": policy.get("storageClass"),
            "uniform_bucket_level_access": True,
            "public_access_prevention": "enforced",
            "object_versioning": False,
        }
        if write_probe:
            payload = canonical_bytes({
                "classification": "SYNTHETIC_VALIDATION_OBJECT_NOT_D1_EVIDENCE",
                "backend_identity": GCS_BACKEND_IDENTITY,
                "backend_version": GCS_BACKEND_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "purpose": "D1_DURABLE_STORAGE_WRITE_READBACK_PROBE_V1",
            })
            metadata = self._metadata(
                kind="ACCESS_PROBE",
                digest=sha256(payload).hexdigest(),
                classification="SYNTHETIC_VALIDATION_OBJECT_NOT_D1_EVIDENCE",
            )
            _, created = self._write_once("system/validation/access-probe-v1.json", payload, metadata=metadata)
            result["write_readback_probe"] = True
            result["probe_status"] = "CREATED_AND_VERIFIED" if created else "IDEMPOTENT_AND_VERIFIED"
        return result

    def _metadata(
        self,
        *,
        kind: str,
        digest: str,
        classification: str,
        market: str | None = None,
        session_date: str | None = None,
    ) -> dict[str, str]:
        value = {
            GCS_META_BACKEND: GCS_BACKEND_IDENTITY,
            GCS_META_BACKEND_VERSION: GCS_BACKEND_VERSION,
            GCS_META_KIND: str(kind),
            GCS_META_PROTOCOL: PROTOCOL_VERSION,
            GCS_META_SHA256: str(digest),
            GCS_META_CLASSIFICATION: str(classification),
        }
        if market is not None:
            value[GCS_META_MARKET] = str(market).upper()
        if session_date is not None:
            value[GCS_META_SESSION] = str(session_date)
        return value

    @staticmethod
    def _metadata_matches(actual: Mapping[str, Any], expected: Mapping[str, str]) -> bool:
        return all(str(actual.get(key, "")) == str(value) for key, value in expected.items())

    def _write_once(
        self,
        name: str,
        payload: bytes,
        *,
        metadata: Mapping[str, str],
    ) -> tuple[GcsObject, bool]:
        # The API call itself is the race-safe create-only operation.  There is
        # deliberately no list-before-write existence check here.
        try:
            created = self.api.create_object(self.bucket, name, payload, metadata=metadata)
            if created.payload != payload or not self._metadata_matches(created.metadata, metadata):
                raise D1IntegrityError(f"GCS read-back mismatch: {name}")
            return created, True
        except GcsPreconditionFailed:
            existing = self.api.get_object(self.bucket, name)
            if existing.payload != payload or not self._metadata_matches(existing.metadata, metadata):
                raise D1IntegrityError(f"immutable GCS object mismatch: {name}")
            return existing, False

    def _read_verified(self, name: str, *, metadata: Mapping[str, str]) -> GcsObject:
        value = self.api.get_object(self.bucket, name)
        if not self._metadata_matches(value.metadata, metadata):
            raise D1IntegrityError(f"GCS metadata mismatch: {name}")
        expected_hash = str(metadata[GCS_META_SHA256])
        if sha256(value.payload).hexdigest() != expected_hash:
            raise D1IntegrityError(f"GCS object hash mismatch: {name}")
        return value

    def validate_durable_storage(self, *, expected_bucket_identity_sha256: str | None = None) -> dict[str, Any]:
        """Exercise a synthetic object and independent local recovery only."""

        if expected_bucket_identity_sha256 is not None and self.bucket_identity_sha256 != expected_bucket_identity_sha256:
            raise D1IntegrityError("configured D1 bucket differs from expected bucket identity")
        frozen = verify_frozen_protocol()
        access = self.verify_access(write_probe=True)
        existing_sessions = self.verify()
        if existing_sessions["session_counts"] != {"CN": 0, "US": 0}:
            raise D1IntegrityError("synthetic validation requires an empty formal D1 session graph")
        name = "system/validation/gcs-durable-validation-v1.json"
        payload = canonical_bytes({
            "classification": "SYNTHETIC_VALIDATION_OBJECT_NOT_D1_EVIDENCE",
            "backend_identity": GCS_BACKEND_IDENTITY,
            "backend_version": GCS_BACKEND_VERSION,
            "protocol_version": PROTOCOL_VERSION,
        })
        digest = sha256(payload).hexdigest()
        metadata = self._metadata(
            kind="VALIDATION_ONLY",
            digest=digest,
            classification="SYNTHETIC_VALIDATION_OBJECT_NOT_D1_EVIDENCE",
        )
        object_value, created = self._write_once(name, payload, metadata=metadata)
        replay, replay_created = self._write_once(name, payload, metadata=metadata)
        if replay_created or replay.generation != object_value.generation:
            raise D1IntegrityError("GCS validation idempotency failed")
        try:
            self._write_once(name, payload + b" ", metadata=metadata)
        except D1IntegrityError:
            conflict_failed_closed = True
        else:
            raise D1IntegrityError("GCS create-only identity accepted different bytes")
        read_back = self._read_verified(name, metadata=metadata)
        with TemporaryDirectory() as directory:
            recovered = Path(directory) / "validation-object.json"
            recovered.write_bytes(read_back.payload)
            if sha256(recovered.read_bytes()).hexdigest() != digest:
                raise D1IntegrityError("clean-directory validation recovery hash mismatch")
        graph = self.verify()
        if graph["status"] != "VERIFIED" or graph["session_counts"] != {"CN": 0, "US": 0}:
            raise D1IntegrityError("GCS session graph verification failed")
        return {
            "status": "VERIFIED",
            "classification": "SYNTHETIC_VALIDATION_OBJECT_NOT_D1_EVIDENCE",
            "backend_identity": GCS_BACKEND_IDENTITY,
            "backend_version": GCS_BACKEND_VERSION,
            "bucket": self.bucket,
            "bucket_identity_sha256": self.bucket_identity_sha256,
            "bucket_policy": {
                "location": access["bucket_location"],
                "storage_class": access["storage_class"],
                "uniform_bucket_level_access": True,
                "public_access_prevention": "enforced",
                "object_versioning": False,
            },
            "object_name": name,
            "object_generation": read_back.generation,
            "object_sha256": digest,
            "create_status": "CREATED" if created else "IDEMPOTENT_REPLAY",
            "read_back_hash_match": True,
            "idempotent_rerun": True,
            "clean_directory_recovery": True,
            "different_content_fail_closed": conflict_failed_closed,
            "session_counts": graph["session_counts"],
            **frozen,
        }

    def _activation_name(self, market: str) -> str:
        normalized = str(market).upper()
        if normalized not in {"CN", "US"}:
            raise ValueError("market must be CN or US")
        return f"system/activation/{normalized}.json"

    def create_activation_record(
        self,
        *,
        market: str,
        activation_timestamp: str,
        code_sha: str,
        source_contract: Mapping[str, Any],
        observer_version: str,
    ) -> dict[str, Any]:
        """Create one immutable market activation record after storage validation."""

        require_approved_formal_backend()
        validation = self.validate_durable_storage()
        if validation["status"] != "VERIFIED":
            raise D1IntegrityError("GCS_DURABLE_STORAGE_NOT_VERIFIED")
        record = build_activation_record(
            market=market,
            activation_timestamp=activation_timestamp,
            backend_identity=GCS_BACKEND_IDENTITY,
            backend_version=GCS_BACKEND_VERSION,
            storage_identity_sha256=self.bucket_identity_sha256,
            code_sha=code_sha,
            source_contract=source_contract,
            observer_version=observer_version,
        )
        name = self._activation_name(market)
        payload = canonical_bytes(record)
        metadata = self._metadata(
            kind="ACTIVATION_RECORD",
            digest=sha256(payload).hexdigest(),
            classification="PUBLIC_MARKET_RESEARCH_ONLY_NO_HOLDINGS",
            market=market,
        )
        value, _ = self._write_once(name, payload, metadata=metadata)
        loaded = self._read_verified(name, metadata=metadata)
        if loaded.generation != value.generation:
            raise D1IntegrityError("activation record generation changed")
        return record

    def load_activation_record(self, market: str) -> dict[str, Any]:
        name = self._activation_name(market)
        value = self.api.get_object(self.bucket, name)
        record = json.loads(value.payload)
        validate_activation_record(
            record,
            expected_backend_identity=GCS_BACKEND_IDENTITY,
            expected_backend_version=GCS_BACKEND_VERSION,
            expected_storage_identity_sha256=self.bucket_identity_sha256,
        )
        expected = self._metadata(
            kind="ACTIVATION_RECORD",
            digest=sha256(value.payload).hexdigest(),
            classification="PUBLIC_MARKET_RESEARCH_ONLY_NO_HOLDINGS",
            market=market,
        )
        if not self._metadata_matches(value.metadata, expected):
            raise D1IntegrityError("activation record metadata mismatch")
        return dict(record)

    def _validate_formal_snapshot(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        validate_session_snapshot(snapshot)
        if not snapshot.get("prospective_eligible") or snapshot.get("capture_status") != "COMPLETE":
            raise D1IntegrityError("D1 formal GCS commit requires a complete natural session")
        source = snapshot.get("source_identity") or {}
        if source.get("source_contract_version") != D1_SOURCE_CONTRACT_VERSION:
            raise D1IntegrityError("D1_SOURCE_ACTIVATION_CONTRACT_PENDING")
        if not source.get("activation_record_sha256"):
            raise D1IntegrityError("D1 activation record binding is missing")
        components = snapshot.get("components") or {}
        for name in ("raw_source_snapshot", "normalized_prefix_snapshot", "decision_snapshot", "research_observation_report"):
            payload = (components.get(name) or {}).get("payload") or {}
            if payload.get("contract_version") != D1_SOURCE_CONTRACT_VERSION or payload.get("status") != "VERIFIED":
                raise D1IntegrityError(f"D1 source contract incomplete: {name}")
        report = (components["research_observation_report"]["payload"] or {})
        if not report.get("observer_version") or not report.get("report_markdown"):
            raise D1IntegrityError("D1 observer/report contract incomplete")
        return dict(source)

    def _object_name(self, digest: str) -> str:
        return f"objects/{digest}.json"

    def _commit_name(self, market: str, session_date: str) -> str:
        return f"sessions/{str(market).upper()}/{session_date}.json"

    def commit(self, snapshot: Mapping[str, Any]) -> GcsCommitResult:
        require_approved_formal_backend()
        source = self._validate_formal_snapshot(snapshot)
        market = str(snapshot["market"]).upper()
        session_text = str(snapshot["session_date"])
        try:
            activation = self.load_activation_record(market)
        except GcsNotFound as exc:
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

        digest = str(snapshot["event_sha256"])
        object_payload = canonical_bytes(snapshot)
        object_sha256 = sha256(object_payload).hexdigest()
        object_name = self._object_name(object_sha256)
        classification = str(snapshot["data_classification"])
        object_metadata = self._metadata(
            kind="OBJECT",
            digest=object_sha256,
            classification=classification,
            market=market,
            session_date=session_text,
        )
        object_value, _ = self._write_once(
            object_name, object_payload, metadata=object_metadata
        )
        pointer = {
            "schema_version": "setup01-d1-session-commit-gcs-v1",
            "backend_identity": GCS_BACKEND_IDENTITY,
            "backend_version": GCS_BACKEND_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "event_id": snapshot["event_id"],
            "event_sha256": digest,
            "market": market,
            "session_date": session_text,
            "object_name": object_name,
            "object_generation": object_value.generation,
            "object_sha256": object_sha256,
            "classification": classification,
        }
        pointer["commit_sha256"] = content_sha256(pointer)
        commit_name = self._commit_name(market, session_text)
        pointer_metadata = self._metadata(
            kind="SESSION_COMMIT",
            digest=pointer["commit_sha256"],
            classification=classification,
            market=market,
            session_date=session_text,
        )
        commit_value, created = self._write_once(
            commit_name, canonical_bytes(pointer), metadata=pointer_metadata
        )
        # Read both sides after the pointer write so a partial or stale graph
        # cannot be reported as committed.
        self.load(market, date.fromisoformat(session_text))
        return GcsCommitResult(
            "COMMITTED" if created else "IDEMPOTENT_REPLAY",
            str(snapshot["event_id"]),
            digest,
            object_name,
            object_value.generation,
            commit_name,
            commit_value.generation,
        )

    def _load_pointer(self, market: str, session_date: date) -> tuple[dict[str, Any], GcsObject]:
        name = self._commit_name(market, session_date.isoformat())
        try:
            value = self.api.get_object(self.bucket, name)
        except GcsNotFound as exc:
            raise FileNotFoundError(f"missing D1 session: {market}:{session_date.isoformat()}") from exc
        pointer = json.loads(value.payload)
        without_hash = dict(pointer)
        actual = without_hash.pop("commit_sha256", None)
        if actual != content_sha256(without_hash):
            raise D1IntegrityError("GCS commit hash mismatch")
        expected = self._metadata(
            kind="SESSION_COMMIT",
            digest=str(pointer.get("commit_sha256") or ""),
            classification=str(pointer.get("classification") or ""),
            market=market,
            session_date=session_date.isoformat(),
        )
        if not self._metadata_matches(value.metadata, expected):
            raise D1IntegrityError("GCS commit metadata mismatch")
        return pointer, value

    def load(self, market: str, session_date: date) -> dict[str, Any]:
        pointer, _ = self._load_pointer(market, session_date)
        if pointer.get("backend_identity") != GCS_BACKEND_IDENTITY:
            raise D1IntegrityError("GCS pointer backend identity mismatch")
        if pointer.get("backend_version") != GCS_BACKEND_VERSION:
            raise D1IntegrityError("GCS pointer backend version mismatch")
        if pointer.get("protocol_version") != PROTOCOL_VERSION:
            raise D1IntegrityError("GCS pointer protocol mismatch")
        if pointer.get("market") != str(market).upper():
            raise D1IntegrityError("GCS pointer market mismatch")
        if pointer.get("session_date") != session_date.isoformat():
            raise D1IntegrityError("GCS pointer session mismatch")
        object_name = str(pointer.get("object_name") or "")
        if not object_name.startswith("objects/"):
            raise D1IntegrityError("GCS pointer object path is outside D1 objects prefix")
        try:
            value = self.api.get_object(self.bucket, object_name)
        except GcsNotFound as exc:
            raise D1IntegrityError("GCS session object is missing") from exc
        if str(value.generation) != str(pointer.get("object_generation")):
            raise D1IntegrityError("GCS object generation mismatch")
        if sha256(value.payload).hexdigest() != str(pointer.get("object_sha256")):
            raise D1IntegrityError("GCS commit/object hash mismatch")
        expected = self._metadata(
            kind="OBJECT",
            digest=str(pointer.get("object_sha256") or ""),
            classification=str(pointer.get("classification") or ""),
            market=str(pointer.get("market") or market),
            session_date=str(pointer.get("session_date") or session_date.isoformat()),
        )
        if not self._metadata_matches(value.metadata, expected):
            raise D1IntegrityError("GCS object metadata mismatch")
        snapshot = json.loads(value.payload)
        validate_session_snapshot(snapshot)
        if snapshot.get("event_sha256") != pointer.get("event_sha256"):
            raise D1IntegrityError("GCS event identity mismatch")
        return snapshot

    def verify(self, expected_sessions: Mapping[str, Iterable[date]] | None = None) -> dict[str, Any]:
        found: dict[str, set[str]] = {"CN": set(), "US": set()}
        errors: list[str] = []
        for market in ("CN", "US"):
            try:
                items = self.api.list_objects(self.bucket, prefix=f"sessions/{market}/")
            except GcsNotFound:
                items = []
            for item in items:
                name = str(item.get("name") or "")
                try:
                    session = date.fromisoformat(Path(name).stem)
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
                    if session.isoformat() not in found.get(str(market).upper(), set()):
                        missing.append(f"{str(market).upper()}:{session.isoformat()}")
        return {
            "status": "VERIFIED" if not errors and not missing else "FAILED",
            "backend_identity": GCS_BACKEND_IDENTITY,
            "backend_version": GCS_BACKEND_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "bucket_identity_sha256": self.bucket_identity_sha256,
            "session_counts": {market: len(values) for market, values in found.items()},
            "missing_sessions": missing,
            "errors": errors,
        }

    def recover_to(self, target: str | Path) -> dict[str, Any]:
        source_check = self.verify()
        if source_check["status"] != "VERIFIED":
            raise D1IntegrityError("source GCS store failed verification")
        destination = Path(target)
        if destination.exists() and any(destination.iterdir()):
            raise D1IntegrityError("recovery target must be empty")
        destination.mkdir(parents=True, exist_ok=True)
        filesystem = FilesystemD1Store(destination)
        for market in ("CN", "US"):
            for session_text in sorted(self._session_names(market)):
                filesystem.commit(self.load(market, date.fromisoformat(session_text)))
        recovered = filesystem.verify()
        if (
            recovered["status"] != source_check["status"]
            or recovered["protocol_version"] != source_check["protocol_version"]
            or recovered["session_counts"] != source_check["session_counts"]
            or recovered["missing_sessions"] != source_check["missing_sessions"]
            or recovered["errors"] != source_check["errors"]
        ):
            raise D1IntegrityError("GCS recovery verification mismatch")
        return recovered

    def _session_names(self, market: str) -> set[str]:
        return {
            Path(str(item.get("name") or "")).stem
            for item in self.api.list_objects(self.bucket, prefix=f"sessions/{str(market).upper()}/")
            if str(item.get("name") or "").endswith(".json")
        }


__all__ = [
    "D1GcsApi",
    "GCS_BACKEND_IDENTITY",
    "GCS_BACKEND_VERSION",
    "GCS_SCOPE",
    "GcsApiError",
    "GcsNotFound",
    "GcsObject",
    "GcsPreconditionFailed",
    "GoogleCloudStorageApi",
    "GoogleCloudStorageD1Store",
    "GcsCommitResult",
    "bucket_identity_sha256",
    "require_approved_formal_backend",
]
