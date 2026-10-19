"""Read-only access to the TCC SQLite database."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from tcc_permission_assistant.core.errors import (
    TCCDatabaseAccessError,
    TCCDatabaseCorrupt,
    TCCDatabaseError,
    TCCDatabaseLocked,
    TCCDatabaseNotFound,
    TCCQueryError,
    TCCSchemaError,
)
from tcc_permission_assistant.core.models import (
    AccessColumn,
    AccessSchema,
    DatabaseInspection,
    PermissionLookup,
    PermissionStatus,
    ServiceRecordCount,
    TCCDatabaseScope,
    TCCRecord,
    TCCService,
)
from tcc_permission_assistant.core.permission_map import (
    resolve_service,
    supported_services,
)
from tcc_permission_assistant.core.security import validate_bundle_id

USER_TCC_RELATIVE_PATH = Path("Library/Application Support/com.apple.TCC/TCC.db")
SYSTEM_TCC_PATH = Path("/Library/Application Support/com.apple.TCC/TCC.db")
REQUIRED_ACCESS_COLUMNS = ("service", "client", "auth_value")
OPTIONAL_RECORD_COLUMNS = (
    "client_type",
    "auth_reason",
    "auth_version",
    "last_modified",
    "indirect_object_identifier",
)


def tcc_database_path(
    scope: TCCDatabaseScope | str,
    home: Path | None = None,
) -> Path:
    """Return the standard database path for a supported scope."""

    parsed_scope = _parse_scope(scope)
    if parsed_scope is TCCDatabaseScope.SYSTEM:
        return SYSTEM_TCC_PATH
    return (home or Path.home()) / USER_TCC_RELATIVE_PATH


class TCCDatabase:
    """Inspect a TCC database without obtaining write access."""

    def __init__(
        self,
        path: str | Path,
        scope: TCCDatabaseScope | str = TCCDatabaseScope.USER,
    ) -> None:
        self.path = Path(path).expanduser().absolute()
        self.scope = _parse_scope(scope)

    @classmethod
    def for_scope(
        cls,
        scope: TCCDatabaseScope | str,
        home: Path | None = None,
    ) -> TCCDatabase:
        parsed_scope = _parse_scope(scope)
        return cls(tcc_database_path(parsed_scope, home=home), parsed_scope)

    def inspect(self) -> DatabaseInspection:
        """Read the access schema, row count, and allowlisted service counts."""

        with self._read_connection() as connection:
            schema = self._read_access_schema(connection)
            row_count = self._scalar_int(
                connection.execute("SELECT COUNT(*) FROM access").fetchone(),
                "access 记录总数",
            )
            service_counts = self._read_supported_service_counts(connection)

        try:
            size_bytes = self.path.stat().st_size
        except OSError:
            size_bytes = None
        return DatabaseInspection(
            path=self.path,
            scope=self.scope,
            schema=schema,
            access_row_count=row_count,
            supported_service_counts=service_counts,
            size_bytes=size_bytes,
        )

    def lookup_permissions(
        self,
        client: str,
        services: Sequence[TCCService | str] | None = None,
    ) -> tuple[PermissionLookup, ...]:
        """Return one lookup result per requested allowlisted service."""

        bundle_id = validate_bundle_id(client)
        selected_services = _normalize_services(services)
        with self._read_connection() as connection:
            schema = self._read_access_schema(connection)
            records = self._query_records(
                connection,
                schema,
                bundle_id,
                selected_services,
            )

        records_by_service: dict[TCCService, list[TCCRecord]] = {
            service: [] for service in selected_services
        }
        for record in records:
            records_by_service[record.service].append(record)
        return tuple(
            PermissionLookup(
                client=bundle_id,
                service=service,
                records=tuple(records_by_service[service]),
            )
            for service in selected_services
        )

    def lookup_permission_statuses_for_clients(
        self,
        clients: Sequence[str],
        services: Sequence[TCCService | str] | None = None,
    ) -> dict[str, dict[TCCService, PermissionStatus]]:
        """Return status maps for many clients using one read connection."""

        validated_clients: list[str] = []
        for client in clients:
            validated = validate_bundle_id(client)
            if validated not in validated_clients:
                validated_clients.append(validated)
        selected_services = _normalize_services(services)
        result = {
            client: {
                service: PermissionStatus.NO_RECORD for service in selected_services
            }
            for client in validated_clients
        }
        if not validated_clients:
            return result

        with self._read_connection() as connection:
            client_placeholders = ", ".join("?" for _ in validated_clients)
            service_placeholders = ", ".join("?" for _ in selected_services)
            try:
                rows = connection.execute(
                    "SELECT client, service, auth_value FROM access "
                    f"WHERE client IN ({client_placeholders}) "
                    f"AND service IN ({service_placeholders})",
                    (
                        *validated_clients,
                        *(service.value for service in selected_services),
                    ),
                ).fetchall()
            except sqlite3.Error as exc:
                raise TCCQueryError("批量查询 TCC 权限记录失败。") from exc

        observed: dict[tuple[str, TCCService], set[PermissionStatus]] = {}
        for client, service_value, auth_value in rows:
            try:
                service = TCCService(str(service_value))
            except ValueError as exc:
                raise TCCQueryError("数据库返回了白名单之外的 TCC service。") from exc
            observed.setdefault((str(client), service), set()).add(
                PermissionStatus.from_auth_value(auth_value)
            )
        for (client, service), statuses in observed.items():
            result[client][service] = (
                next(iter(statuses)) if len(statuses) == 1 else PermissionStatus.UNKNOWN
            )
        return result

    def read_access_schema(self) -> AccessSchema:
        """Return the current access schema without querying client data."""

        with self._read_connection() as connection:
            return self._read_access_schema(connection)

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        self._ensure_exists()
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                f"{self.path.as_uri()}?mode=ro",
                uri=True,
                timeout=1.0,
            )
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA busy_timeout = 1000")
            yield connection
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc
        finally:
            if connection is not None:
                connection.close()

    def _ensure_exists(self) -> None:
        try:
            exists = self.path.is_file()
        except OSError as exc:
            raise TCCDatabaseAccessError(f"无法检查 TCC 数据库：{self.path}") from exc
        if not exists:
            raise TCCDatabaseNotFound(f"TCC 数据库不存在：{self.path}")

    @staticmethod
    def _read_access_schema(connection: sqlite3.Connection) -> AccessSchema:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'access' LIMIT 1"
        ).fetchone()
        if table_exists is None:
            raise TCCSchemaError("TCC 数据库中缺少 access 表。")

        rows = connection.execute("PRAGMA table_info(access)").fetchall()
        columns = tuple(
            AccessColumn(
                cid=int(row[0]),
                name=str(row[1]),
                type_name=str(row[2] or ""),
                not_null=bool(row[3]),
                default_value=row[4],
                primary_key=bool(row[5]),
            )
            for row in rows
        )
        missing = [
            name
            for name in REQUIRED_ACCESS_COLUMNS
            if name not in {column.name for column in columns}
        ]
        if missing:
            raise TCCSchemaError("access 表缺少必需字段：" + ", ".join(missing))
        return AccessSchema(columns=columns)

    @staticmethod
    def _query_records(
        connection: sqlite3.Connection,
        schema: AccessSchema,
        client: str,
        services: Sequence[TCCService],
    ) -> tuple[TCCRecord, ...]:
        selected_columns = list(REQUIRED_ACCESS_COLUMNS)
        selected_columns.extend(
            name for name in OPTIONAL_RECORD_COLUMNS if schema.has_column(name)
        )
        service_placeholders = ", ".join("?" for _ in services)
        statement = (
            f"SELECT {', '.join(selected_columns)} "
            "FROM access "
            f"WHERE client = ? AND service IN ({service_placeholders}) "
            "ORDER BY service"
        )
        try:
            rows = connection.execute(
                statement,
                (client, *(service.value for service in services)),
            ).fetchall()
        except sqlite3.Error as exc:
            raise TCCQueryError("查询 TCC 权限记录失败。") from exc

        records: list[TCCRecord] = []
        for row in rows:
            values = dict(zip(selected_columns, row, strict=True))
            try:
                service = TCCService(values["service"])
            except ValueError as exc:
                raise TCCQueryError("数据库返回了白名单之外的 TCC service。") from exc
            records.append(
                TCCRecord(
                    service=service,
                    client=str(values["client"]),
                    auth_value=values["auth_value"],
                    auth_reason=values.get("auth_reason"),
                    auth_version=values.get("auth_version"),
                    client_type=values.get("client_type"),
                    indirect_object_identifier=values.get("indirect_object_identifier"),
                    last_modified=values.get("last_modified"),
                )
            )
        return tuple(records)

    @staticmethod
    def _read_supported_service_counts(
        connection: sqlite3.Connection,
    ) -> tuple[ServiceRecordCount, ...]:
        services = supported_services()
        placeholders = ", ".join("?" for _ in services)
        rows = connection.execute(
            "SELECT service, COUNT(*) FROM access "
            f"WHERE service IN ({placeholders}) GROUP BY service",
            tuple(service.value for service in services),
        ).fetchall()
        counts = {str(row[0]): int(row[1]) for row in rows}
        return tuple(
            ServiceRecordCount(service=service, count=counts.get(service.value, 0))
            for service in services
        )

    @staticmethod
    def _scalar_int(row: sqlite3.Row | tuple[object, ...] | None, label: str) -> int:
        if row is None:
            raise TCCQueryError(f"无法读取{label}。")
        try:
            return int(row[0])
        except (TypeError, ValueError, IndexError) as exc:
            raise TCCQueryError(f"{label}格式异常。") from exc


def _parse_scope(value: TCCDatabaseScope | str) -> TCCDatabaseScope:
    if isinstance(value, TCCDatabaseScope):
        return value
    try:
        return TCCDatabaseScope(value.strip().casefold())
    except ValueError as exc:
        raise TCCDatabaseError(f"不支持的 TCC 数据库作用域：{value}") from exc


def _normalize_services(
    services: Sequence[TCCService | str] | None,
) -> tuple[TCCService, ...]:
    if services is None:
        return supported_services()
    normalized: list[TCCService] = []
    for item in services:
        service = resolve_service(item)
        if service not in normalized:
            normalized.append(service)
    if not normalized:
        raise TCCDatabaseError("至少需要选择一个 TCC service。")
    return tuple(normalized)


def _map_sqlite_error(error: sqlite3.Error) -> TCCDatabaseError:
    message = str(error)
    lowered = message.casefold()
    if "locked" in lowered or "busy" in lowered:
        return TCCDatabaseLocked("TCC 数据库正被占用或锁定，请稍后重试。")
    if (
        "unable to open" in lowered
        or "authorization denied" in lowered
        or "not authorized" in lowered
        or "permission" in lowered
    ):
        return TCCDatabaseAccessError(
            "无法只读打开 TCC 数据库。请检查完全磁盘访问权限和文件权限。"
        )
    if (
        "malformed" in lowered
        or "corrupt" in lowered
        or "file is not a database" in lowered
    ):
        return TCCDatabaseCorrupt("TCC 数据库文件可能已损坏。")
    return TCCDatabaseError(f"读取 TCC 数据库失败：{message}")
