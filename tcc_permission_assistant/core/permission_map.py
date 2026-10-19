"""Fixed mappings between app declarations and TCC services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from tcc_permission_assistant.core.errors import UnsupportedService
from tcc_permission_assistant.core.models import TCCService


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    """User-facing and CLI details for an allowlisted TCC service."""

    service: TCCService
    display_name: str
    cli_name: str


SERVICE_DEFINITIONS: tuple[ServiceDefinition, ...] = (
    ServiceDefinition(TCCService.CAMERA, "摄像头", "Camera"),
    ServiceDefinition(TCCService.MICROPHONE, "麦克风", "Microphone"),
    ServiceDefinition(TCCService.APPLE_EVENTS, "自动化 / Apple Events", "AppleEvents"),
    ServiceDefinition(TCCService.DESKTOP_FOLDER, "桌面文件夹", "DesktopFolder"),
    ServiceDefinition(TCCService.DOCUMENTS_FOLDER, "文稿文件夹", "DocumentsFolder"),
    ServiceDefinition(TCCService.DOWNLOADS_FOLDER, "下载文件夹", "DownloadsFolder"),
    ServiceDefinition(TCCService.REMOVABLE_VOLUMES, "可移除卷", "RemovableVolumes"),
)

SERVICE_DEFINITION_BY_SERVICE: Mapping[TCCService, ServiceDefinition] = (
    MappingProxyType(
        {definition.service: definition for definition in SERVICE_DEFINITIONS}
    )
)

USAGE_DESCRIPTION_TO_SERVICE: Mapping[str, TCCService] = MappingProxyType(
    {
        "NSCameraUsageDescription": TCCService.CAMERA,
        "NSMicrophoneUsageDescription": TCCService.MICROPHONE,
        "NSAppleEventsUsageDescription": TCCService.APPLE_EVENTS,
        "NSDesktopFolderUsageDescription": TCCService.DESKTOP_FOLDER,
        "NSDocumentsFolderUsageDescription": TCCService.DOCUMENTS_FOLDER,
        "NSDownloadsFolderUsageDescription": TCCService.DOWNLOADS_FOLDER,
        "NSRemovableVolumesUsageDescription": TCCService.REMOVABLE_VOLUMES,
    }
)

ENTITLEMENT_TO_SERVICE: Mapping[str, TCCService] = MappingProxyType(
    {
        "com.apple.security.device.camera": TCCService.CAMERA,
        "com.apple.security.device.audio-input": TCCService.MICROPHONE,
    }
)


def _build_service_aliases() -> dict[str, TCCService]:
    aliases: dict[str, TCCService] = {}
    extra_aliases = {
        TCCService.CAMERA: ("camera", "摄像头"),
        TCCService.MICROPHONE: ("microphone", "audio", "麦克风"),
        TCCService.APPLE_EVENTS: ("appleevents", "apple-events", "automation"),
        TCCService.DESKTOP_FOLDER: ("desktop", "desktopfolder"),
        TCCService.DOCUMENTS_FOLDER: ("documents", "documentsfolder"),
        TCCService.DOWNLOADS_FOLDER: ("downloads", "downloadsfolder"),
        TCCService.REMOVABLE_VOLUMES: (
            "removable",
            "removablevolumes",
            "removable-volumes",
        ),
    }
    for definition in SERVICE_DEFINITIONS:
        aliases[definition.service.value.casefold()] = definition.service
        aliases[definition.service.name.casefold()] = definition.service
        aliases[definition.cli_name.casefold()] = definition.service
        for alias in extra_aliases[definition.service]:
            aliases[alias.casefold()] = definition.service
    return aliases


_SERVICE_ALIASES: Mapping[str, TCCService] = MappingProxyType(_build_service_aliases())


def get_service_definition(service: TCCService) -> ServiceDefinition:
    """Return display details for a known service."""

    return SERVICE_DEFINITION_BY_SERVICE[service]


def resolve_service(value: str | TCCService) -> TCCService:
    """Resolve a CLI/display alias without allowing arbitrary service names."""

    if isinstance(value, TCCService):
        return value
    normalized = value.strip().casefold()
    try:
        return _SERVICE_ALIASES[normalized]
    except KeyError as exc:
        raise UnsupportedService(f"不支持的 TCC service：{value}") from exc


def supported_services() -> tuple[TCCService, ...]:
    """Return the complete service allowlist in display order."""

    return tuple(definition.service for definition in SERVICE_DEFINITIONS)
