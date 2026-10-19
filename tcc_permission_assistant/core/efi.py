"""Read, mount, and unmount macOS EFI system partitions."""

from __future__ import annotations

import plistlib
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tcc_permission_assistant.core.errors import TCCAssistantError

DISKUTIL = "/usr/sbin/diskutil"
OSASCRIPT = "/usr/bin/osascript"
EFI_IDENTIFIER_PATTERN = re.compile(r"^disk[0-9]+s[0-9]+$")

_PRIVILEGED_EFI_SCRIPT = """
on run argv
    set operationName to item 1 of argv
    set targetDisk to item 2 of argv
    if operationName is "mount" then
        do shell script "/usr/sbin/diskutil mount " & quoted form of targetDisk with administrator privileges
    else if operationName is "unmount" then
        do shell script "/usr/sbin/diskutil unmount " & quoted form of targetDisk with administrator privileges
    else
        error "Unsupported EFI operation"
    end if
end run
""".strip()


class EFIError(TCCAssistantError):
    """An EFI partition operation failed or was rejected."""


@dataclass(frozen=True, slots=True)
class EFICommandResult:
    returncode: int
    stdout: str
    stderr: str


class EFICommandRunner(Protocol):
    def run(self, command: Sequence[str]) -> EFICommandResult:
        """Run one diskutil or osascript command without a shell."""


class SubprocessEFIRunner:
    def __init__(self, timeout_seconds: float = 120.0) -> None:
        self._timeout_seconds = timeout_seconds

    def run(self, command: Sequence[str]) -> EFICommandResult:
        try:
            completed = subprocess.run(
                list(command),
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise EFIError("EFI 操作或管理员授权超时。") from exc
        except OSError as exc:
            raise EFIError(f"无法运行命令：{command[0]}") from exc
        return EFICommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )


@dataclass(frozen=True, slots=True)
class EFIPartition:
    identifier: str
    device_node: str
    disk_identifier: str
    volume_name: str
    size_bytes: int
    mount_point: Path | None
    disk_uuid: str | None
    volume_uuid: str | None

    @property
    def mounted(self) -> bool:
        return self.mount_point is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "device_node": self.device_node,
            "disk_identifier": self.disk_identifier,
            "volume_name": self.volume_name,
            "size_bytes": self.size_bytes,
            "mount_point": (
                str(self.mount_point) if self.mount_point is not None else None
            ),
            "disk_uuid": self.disk_uuid,
            "volume_uuid": self.volume_uuid,
        }


class EFIManager:
    """Discover and manage EFI partitions through diskutil."""

    def __init__(self, runner: EFICommandRunner | None = None) -> None:
        self.runner = runner or SubprocessEFIRunner()

    def list_partitions(self) -> tuple[EFIPartition, ...]:
        result = self.runner.run([DISKUTIL, "list", "-plist", "physical"])
        if result.returncode != 0:
            raise EFIError(
                f"无法读取磁盘列表：{result.stderr.strip() or result.stdout.strip()}"
            )
        try:
            payload = plistlib.loads(result.stdout.encode("utf-8"))
        except (plistlib.InvalidFileException, ValueError) as exc:
            raise EFIError("diskutil 返回的磁盘信息格式无效。") from exc
        if not isinstance(payload, dict):
            raise EFIError("diskutil 磁盘信息根节点格式无效。")

        partitions: list[EFIPartition] = []
        for disk in payload.get("AllDisksAndPartitions", []):
            if not isinstance(disk, dict):
                continue
            disk_identifier = str(disk.get("DeviceIdentifier", ""))
            for item in disk.get("Partitions", []):
                if not isinstance(item, dict):
                    continue
                if str(item.get("Content", "")).casefold() != "efi":
                    continue
                identifier = str(item.get("DeviceIdentifier", ""))
                if not EFI_IDENTIFIER_PATTERN.fullmatch(identifier):
                    continue
                mount_value = item.get("MountPoint")
                mount_point = Path(str(mount_value)) if mount_value else None
                partitions.append(
                    EFIPartition(
                        identifier=identifier,
                        device_node=f"/dev/{identifier}",
                        disk_identifier=disk_identifier,
                        volume_name=str(item.get("VolumeName") or "EFI"),
                        size_bytes=int(item.get("Size") or 0),
                        mount_point=mount_point,
                        disk_uuid=_optional_text(item.get("DiskUUID")),
                        volume_uuid=_optional_text(item.get("VolumeUUID")),
                    )
                )
        return tuple(sorted(partitions, key=lambda partition: partition.identifier))

    def mount(self, identifier: str, *, confirmed: bool = False) -> EFIPartition:
        if not confirmed:
            raise EFIError("挂载 EFI 前必须获得用户确认。")
        partition = self._find_mountable(identifier)
        if partition.mounted:
            return partition
        self._run_privileged("mount", identifier)
        refreshed = self._find_mountable(identifier)
        if not refreshed.mounted:
            raise EFIError("diskutil 返回成功，但 EFI 分区仍未挂载。")
        return refreshed

    def unmount(
        self,
        identifier: str,
        *,
        confirmed: bool = False,
    ) -> EFIPartition:
        if not confirmed:
            raise EFIError("卸载 EFI 前必须获得用户确认。")
        partition = self._find_mountable(identifier)
        if not partition.mounted:
            return partition
        self._run_privileged("unmount", identifier)
        refreshed = self._find_mountable(identifier)
        if refreshed.mounted:
            raise EFIError("diskutil 返回成功，但 EFI 分区仍处于挂载状态。")
        return refreshed

    def _find_mountable(self, identifier: str) -> EFIPartition:
        if not EFI_IDENTIFIER_PATTERN.fullmatch(identifier):
            raise EFIError("EFI 分区标识格式无效。")
        for partition in self.list_partitions():
            if partition.identifier == identifier:
                return partition
        raise EFIError("未找到指定的 EFI 分区。")

    def _run_privileged(self, operation: str, identifier: str) -> None:
        result = self.runner.run(
            [
                OSASCRIPT,
                "-e",
                _PRIVILEGED_EFI_SCRIPT,
                operation,
                identifier,
            ]
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise EFIError(detail or "管理员授权被取消或 EFI 操作失败。")


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
