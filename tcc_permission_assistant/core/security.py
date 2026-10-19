"""Small security primitives shared by future database operations."""

from __future__ import annotations

import re

from tcc_permission_assistant.core.errors import InvalidBundleID

_BUNDLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,253}[A-Za-z0-9])?$")


def validate_bundle_id(value: object) -> str:
    """Validate a bundle identifier before it reaches generated SQL.

    TCC writes will still use bound SQL parameters in later phases. This check
    additionally rejects malformed identifiers and obvious injection payloads.
    """

    if not isinstance(value, str):
        raise InvalidBundleID("Bundle ID 必须是字符串。")
    candidate = value.strip()
    if not candidate:
        raise InvalidBundleID("Bundle ID 不能为空。")
    if len(candidate) > 255:
        raise InvalidBundleID("Bundle ID 长度不能超过 255 个字符。")
    if ".." in candidate:
        raise InvalidBundleID("Bundle ID 不能包含连续的句点。")
    if not _BUNDLE_ID_PATTERN.fullmatch(candidate):
        raise InvalidBundleID(
            "Bundle ID 仅允许 ASCII 字母、数字、点、连字符和下划线，"
            "且必须以字母或数字开头和结尾。"
        )
    return candidate
