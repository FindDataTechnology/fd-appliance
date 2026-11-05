"""bundle 版本口径（领域无关）：整机包=版本化交付单元，增量=版本化日更形态。

bundle id 形态（tenant 段使多行业线共用一个通道）：
- 全量：``appliance-<tenant>-v<X.Y.Z>``
- 增量：``appliance-<tenant>-v<X.Y.Z>-inc-<YYYY-MM-DD>``
"""

from __future__ import annotations

import re

_VERSION_RE = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_BUNDLE_RE = re.compile(
    r"^appliance-(?P<tenant>[a-z0-9][a-z0-9-]*)-v(?P<version>\d+\.\d+\.\d+)"
    r"(?P<inc>-inc-(?P<as_of>\d{4}-\d{2}-\d{2}))?$"
)


def parse_bundle_version(version: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(version.strip())
    if not match:
        raise ValueError(f"bundle version must be X.Y.Z, got {version!r}")
    return int(match["major"]), int(match["minor"]), int(match["patch"])


def bundle_id(tenant: str, version: str, *, form: str = "full", as_of: str | None = None) -> str:
    parse_bundle_version(version)
    if not _TENANT_RE.match(tenant):
        raise ValueError(f"tenant must be kebab-case, got {tenant!r}")
    if form not in ("full", "incremental"):
        raise ValueError(f"form must be full|incremental, got {form!r}")
    base = f"appliance-{tenant}-v{version}"
    if form == "incremental":
        if not as_of or not re.match(r"^\d{4}-\d{2}-\d{2}$", as_of):
            raise ValueError("incremental bundle requires as_of=YYYY-MM-DD")
        return f"{base}-inc-{as_of}"
    return base


def parse_bundle_id(value: str) -> dict[str, str | None]:
    match = _BUNDLE_RE.match(value)
    if not match:
        raise ValueError(f"not an appliance bundle id: {value!r}")
    return {
        "tenant": match["tenant"],
        "version": match["version"],
        "form": "incremental" if match["inc"] else "full",
        "as_of": match["as_of"],
    }
