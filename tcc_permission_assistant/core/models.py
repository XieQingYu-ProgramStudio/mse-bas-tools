"""Data structures shared by the scanner, CLI, and future GUI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class TCCService(str, Enum):
    """TCC services supported by this application."""

    CAMERA = "kTCCServiceCamera"
    MICROPHONE = "kTCCServiceMicrophone"
    APPLE_EVENTS = "kTCCServiceAppleEvents"
    DESKTOP_FOLDER = "kTCCServiceSystemPolicyDesktopFolder"
    DOCUMENTS_FOLDER = "kTCCServiceSystemPolicyDocumentsFolder"
    DOWNLOADS_FOLDER = "kTCCServiceSystemPolicyDownloadsFolder"
    REMOVABLE_VOLUMES = "kTCCServiceSystemPolicyRemovableVolumes"


class PermissionSource(str, Enum):
    """Where a declared permission was found."""

    INFO_PLIST_USAGE = "info_plist_usage_description"
    ENTITLEMENT = "entitlement"


class SigningStatus(str, Enum):
    """High-level code-signing state."""

    SIGNED = "signed"
    ADHOC = "adhoc"
    UNSIGNED = "unsigned"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class PermissionStatus(str, Enum):
    """TCC authorization state for one client and service."""

    NO_RECORD = "no_record"
    ALLOWED = "allowed"
    DENIED = "denied"
    UNKNOWN = "unknown"

    @classmethod
    def from_auth_value(cls, value: object) -> PermissionStatus:
        """Map macOS 15 auth values without hiding system-version differences."""

        if isinstance(value, bool):
            return cls.UNKNOWN
        if value == 2:
            return cls.ALLOWED
        if value == 0:
            return cls.DENIED
        return cls.UNKNOWN


class TCCDatabaseScope(str, Enum):
    """TCC database scope supported by the tool."""

    USER = "user"
    SYSTEM = "system"


class PermissionAction(str, Enum):
    """Authorization value requested by the user."""

    ALLOW = "allow"
    DENY = "deny"
    DELETE = "delete"

    @property
    def auth_value(self) -> int | None:
        if self is PermissionAction.ALLOW:
            return 2
        if self is PermissionAction.DENY:
            return 0
        return None


class InjectionOperation(str, Enum):
    """SQL operation selected from the current database state."""

    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class PermissionDeclaration:
    """A permission declaration found in an application bundle."""

    service: TCCService
    source: PermissionSource
    evidence_key: str
    description: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "service": self.service.value,
            "source": self.source.value,
            "evidence_key": self.evidence_key,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class SigningInfo:
    """Code-signing details used to explain TCC identity risk."""

    status: SigningStatus
    signed: bool
    adhoc: bool
    identifier: str | None = None
    team_id: str | None = None
    authorities: tuple[str, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "signed": self.signed,
            "adhoc": self.adhoc,
            "identifier": self.identifier,
            "team_id": self.team_id,
            "authorities": list(self.authorities),
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class AppScanResult:
    """Read-only result of scanning one macOS application bundle."""

    name: str
    path: Path
    bundle_id: str
    short_version: str | None
    bundle_version: str | None
    signing: SigningInfo
    permissions: tuple[PermissionDeclaration, ...]
    recommended_services: tuple[TCCService, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "application": {
                "name": self.name,
                "path": str(self.path),
                "bundle_id": self.bundle_id,
                "short_version": self.short_version,
                "bundle_version": self.bundle_version,
            },
            "signing": self.signing.to_dict(),
            "permissions": [item.to_dict() for item in self.permissions],
            "recommended_services": [
                service.value for service in self.recommended_services
            ],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class AccessColumn:
    """One dynamically discovered column from ``PRAGMA table_info(access)``."""

    cid: int
    name: str
    type_name: str
    not_null: bool
    default_value: object | None
    primary_key: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "cid": self.cid,
            "name": self.name,
            "type": self.type_name,
            "not_null": self.not_null,
            "default": self.default_value,
            "primary_key": self.primary_key,
        }


@dataclass(frozen=True, slots=True)
class AccessSchema:
    """Dynamically read schema for the TCC ``access`` table."""

    columns: tuple[AccessColumn, ...]

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    def has_column(self, name: str) -> bool:
        return name in self.column_names

    def to_dict(self) -> dict[str, Any]:
        return {"columns": [column.to_dict() for column in self.columns]}


@dataclass(frozen=True, slots=True)
class TCCRecord:
    """One allowlisted row read from the TCC access table."""

    service: TCCService
    client: str
    auth_value: int | str | None
    auth_reason: int | str | None = None
    auth_version: int | str | None = None
    client_type: int | str | None = None
    indirect_object_identifier: int | str | None = None
    last_modified: int | str | None = None

    @property
    def status(self) -> PermissionStatus:
        return PermissionStatus.from_auth_value(self.auth_value)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "service": self.service.value,
            "client": self.client,
            "auth_value": self.auth_value,
            "auth_reason": self.auth_reason,
            "auth_version": self.auth_version,
            "client_type": self.client_type,
            "last_modified": self.last_modified,
            "status": self.status.value,
        }
        if self.indirect_object_identifier is not None:
            payload["indirect_object_identifier"] = self.indirect_object_identifier
        return payload


@dataclass(frozen=True, slots=True)
class PermissionLookup:
    """Authorization state for one client and one service."""

    client: str
    service: TCCService
    records: tuple[TCCRecord, ...]

    @property
    def status(self) -> PermissionStatus:
        if not self.records:
            return PermissionStatus.NO_RECORD
        statuses = {record.status for record in self.records}
        if len(statuses) == 1:
            return statuses.pop()
        return PermissionStatus.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "client": self.client,
            "service": self.service.value,
            "status": self.status.value,
            "records": [record.to_dict() for record in self.records],
        }


@dataclass(frozen=True, slots=True)
class ServiceRecordCount:
    """Number of access rows for one supported service."""

    service: TCCService
    count: int

    def to_dict(self) -> dict[str, Any]:
        return {"service": self.service.value, "count": self.count}


@dataclass(frozen=True, slots=True)
class DatabaseInspection:
    """Read-only summary of a TCC database."""

    path: Path
    scope: TCCDatabaseScope
    schema: AccessSchema
    access_row_count: int
    supported_service_counts: tuple[ServiceRecordCount, ...]
    size_bytes: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "database": {
                "path": str(self.path),
                "scope": self.scope.value,
                "read_only": True,
                "size_bytes": self.size_bytes,
            },
            "access": {
                "row_count": self.access_row_count,
                "schema": self.schema.to_dict(),
            },
            "supported_service_counts": [
                item.to_dict() for item in self.supported_service_counts
            ],
        }


@dataclass(frozen=True, slots=True)
class InjectionPlan:
    """A fully predictable, validated SQL change for one client and service."""

    database_path: Path
    scope: TCCDatabaseScope
    bundle_id: str
    service: TCCService
    action: PermissionAction
    operation: InjectionOperation
    current_status: PermissionStatus
    existing_record_count: int
    statement: str
    parameters: tuple[object, ...]
    literal_sql: str
    reset_command: str
    generated_at_epoch: int
    indirect_object_identifier: str | None = None

    @property
    def auth_value(self) -> int | None:
        return self.action.auth_value

    def to_dict(self) -> dict[str, Any]:
        return {
            "database_path": str(self.database_path),
            "scope": self.scope.value,
            "bundle_id": self.bundle_id,
            "service": self.service.value,
            "action": self.action.value,
            "auth_value": self.auth_value,
            "operation": self.operation.value,
            "current_status": self.current_status.value,
            "existing_record_count": self.existing_record_count,
            "statement": self.statement,
            "parameters": list(self.parameters),
            "literal_sql": self.literal_sql,
            "reset_command": self.reset_command,
            "generated_at_epoch": self.generated_at_epoch,
            "indirect_object_identifier": self.indirect_object_identifier,
        }


@dataclass(frozen=True, slots=True)
class BackupInfo:
    """A verified SQLite backup file."""

    path: Path
    source_path: Path
    scope: TCCDatabaseScope
    created_at: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "source_path": str(self.source_path),
            "scope": self.scope.value,
            "created_at": self.created_at,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class BackupEntry:
    """Metadata for a backup listed from the managed backup directory."""

    path: Path
    scope: TCCDatabaseScope
    size_bytes: int
    modified_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "scope": self.scope.value,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
            "name": self.path.name,
        }


@dataclass(frozen=True, slots=True)
class RestorePlan:
    """A reviewed restore operation for one managed backup."""

    backup_path: Path
    target_path: Path
    scope: TCCDatabaseScope
    current_database_exists: bool
    source_access_row_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "backup_path": str(self.backup_path),
            "target_path": str(self.target_path),
            "scope": self.scope.value,
            "current_database_exists": self.current_database_exists,
            "source_access_row_count": self.source_access_row_count,
            "default_dry_run": True,
        }


@dataclass(frozen=True, slots=True)
class RestoreResult:
    """Outcome of one confirmed restore operation."""

    plan: RestorePlan
    pre_restore_backup: BackupInfo | None
    verified: bool
    access_row_count: int | None
    schema_column_count: int | None
    external_returncode: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.verified,
            "plan": self.plan.to_dict(),
            "pre_restore_backup": (
                self.pre_restore_backup.to_dict()
                if self.pre_restore_backup is not None
                else None
            ),
            "verified": self.verified,
            "access_row_count": self.access_row_count,
            "schema_column_count": self.schema_column_count,
            "external_returncode": self.external_returncode,
        }


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Read-only result of checking a completed injection."""

    success: bool
    expected_status: PermissionStatus
    actual_status: PermissionStatus
    records: tuple[TCCRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "expected_status": self.expected_status.value,
            "actual_status": self.actual_status.value,
            "records": [record.to_dict() for record in self.records],
        }


@dataclass(frozen=True, slots=True)
class InjectionResult:
    """Outcome of one backed-up and verified user-level injection."""

    plan: InjectionPlan
    backup: BackupInfo
    rows_changed: int
    verification: VerificationResult
    rolled_back: bool = False
    rollback_error: str | None = None

    @property
    def success(self) -> bool:
        return self.verification.success

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "plan": self.plan.to_dict(),
            "backup": self.backup.to_dict(),
            "rows_changed": self.rows_changed,
            "verification": self.verification.to_dict(),
            "rolled_back": self.rolled_back,
            "rollback_error": self.rollback_error,
        }


@dataclass(frozen=True, slots=True)
class BatchInjectionResult:
    """Outcome of an atomic multi-application, multi-service injection."""

    plans: tuple[InjectionPlan, ...]
    backup: BackupInfo
    rows_changed: int
    verifications: tuple[VerificationResult, ...]
    rolled_back: bool = False
    rollback_error: str | None = None

    @property
    def success(self) -> bool:
        return bool(self.verifications) and all(
            verification.success for verification in self.verifications
        )

    @property
    def verification_count(self) -> int:
        return len(self.verifications)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "backup": self.backup.to_dict(),
            "rows_changed": self.rows_changed,
            "plan_count": len(self.plans),
            "verification_count": self.verification_count,
            "rolled_back": self.rolled_back,
            "rollback_error": self.rollback_error,
            "plans": [plan.to_dict() for plan in self.plans],
            "verifications": [
                verification.to_dict() for verification in self.verifications
            ],
        }
