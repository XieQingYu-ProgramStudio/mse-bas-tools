"""Small GUI-facing helpers for permission state labels."""

from __future__ import annotations

from collections.abc import Sequence

from tcc_permission_assistant.core.models import (
    PermissionStatus,
    TCCDatabaseScope,
    TCCService,
)
from tcc_permission_assistant.core.tcc_db import TCCDatabase

STATUS_LABELS = {
    PermissionStatus.NO_RECORD: "无记录",
    PermissionStatus.ALLOWED: "允许",
    PermissionStatus.DENIED: "拒绝",
    PermissionStatus.UNKNOWN: "未知",
}

STATUS_BADGE_STATES = {
    PermissionStatus.NO_RECORD: "none",
    PermissionStatus.ALLOWED: "allowed",
    PermissionStatus.DENIED: "denied",
    PermissionStatus.UNKNOWN: "unknown",
}


def permission_statuses(
    bundle_id: str,
    services: Sequence[TCCService],
    database: TCCDatabase | None = None,
) -> dict[TCCService, PermissionStatus]:
    if not services:
        return {}
    active_database = database or TCCDatabase.for_scope(TCCDatabaseScope.USER)
    lookups = active_database.lookup_permissions(bundle_id, services)
    return {lookup.service: lookup.status for lookup in lookups}


def permission_statuses_for_clients(
    bundle_ids: Sequence[str],
    services: Sequence[TCCService],
    database: TCCDatabase | None = None,
) -> dict[str, dict[TCCService, PermissionStatus]]:
    if not bundle_ids or not services:
        return {}
    active_database = database or TCCDatabase.for_scope(TCCDatabaseScope.USER)
    return active_database.lookup_permission_statuses_for_clients(
        bundle_ids,
        services,
    )
