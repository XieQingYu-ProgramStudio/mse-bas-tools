"""Grant the toolbox its own camera and microphone permissions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tcc_permission_assistant.core.backup import BackupManager
from tcc_permission_assistant.core.injector import (
    build_injection_plan,
    execute_dynamic_batch_injection,
)
from tcc_permission_assistant.core.models import (
    BatchInjectionResult,
    PermissionAction,
    PermissionStatus,
    TCCDatabaseScope,
    TCCService,
)
from tcc_permission_assistant.core.tcc_db import TCCDatabase

SELF_BUNDLE_ID = "com.yuexing.bastoolbox"
SELF_TEST_SERVICES = (TCCService.CAMERA, TCCService.MICROPHONE)


@dataclass(frozen=True, slots=True)
class SelfPermissionResult:
    bundle_id: str
    skipped_services: tuple[TCCService, ...]
    injection: BatchInjectionResult | None

    @property
    def success(self) -> bool:
        return self.injection is None or self.injection.success

    @property
    def backup_path(self) -> Path | None:
        return self.injection.backup.path if self.injection is not None else None


def ensure_self_permissions(
    database: TCCDatabase | None = None,
    backup_manager: BackupManager | None = None,
    *,
    bundle_id: str = SELF_BUNDLE_ID,
    services: tuple[TCCService, ...] = SELF_TEST_SERVICES,
) -> SelfPermissionResult:
    """Write allow records for the toolbox itself in one atomic batch."""

    active_database = database or TCCDatabase.for_scope(TCCDatabaseScope.USER)
    lookups = active_database.lookup_permissions(bundle_id, services)
    allowed = {
        lookup.service
        for lookup in lookups
        if lookup.status is PermissionStatus.ALLOWED
    }
    pending = tuple(service for service in services if service not in allowed)
    if not pending:
        return SelfPermissionResult(
            bundle_id=bundle_id,
            skipped_services=tuple(services),
            injection=None,
        )

    plans = tuple(
        build_injection_plan(
            active_database,
            bundle_id,
            service,
            PermissionAction.ALLOW,
        )
        for service in pending
    )
    injection = execute_dynamic_batch_injection(
        plans,
        backup_manager=backup_manager,
    )
    return SelfPermissionResult(
        bundle_id=bundle_id,
        skipped_services=tuple(service for service in services if service in allowed),
        injection=injection,
    )
