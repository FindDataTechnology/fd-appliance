"""交付包 manifest（schema ``vertical-appliance.manifest/v1``）。

组件级 sha256+bytes+provenance；``content_digest``=组件清单规范化摘要。
整包 tar 的摘要放 sidecar ``pack.tar.sha256``（tar 含 manifest 自身，
自引用不可入 manifest——lex 先例同口径）。
"""

from __future__ import annotations

import json
import subprocess
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .hashing import sha256_bytes, sha256_file, file_size
from .manifest_io import canonical_json  # noqa: F401  (re-export)
from .version import bundle_id

MANIFEST_SCHEMA = "vertical-appliance.manifest/v1"
MANIFEST_NAME = "manifest.json"
PACK_FILENAME = "pack.tar"
DIGEST_SIDECAR = "pack.tar.sha256"
CONTENT_DIR = "content"


@dataclass
class Provenance:
    """组件出处三件套：断网验收与同源核对的锚点。"""

    source: str
    stable_id: str
    as_of: str

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "stable_id": self.stable_id, "as_of": self.as_of}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Provenance":
        return cls(
            source=str(payload["source"]),
            stable_id=str(payload["stable_id"]),
            as_of=str(payload["as_of"]),
        )


@dataclass
class Component:
    name: str
    path: str  # 相对 pack 根（content/<file>）
    bytes: int
    sha256: str
    provenance: Provenance | None = None
    tier: str | None = None  # 数据组件的档位（ship_with/online_increment）

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "path": self.path, "bytes": self.bytes, "sha256": self.sha256}
        if self.provenance:
            out["provenance"] = self.provenance.to_dict()
        if self.tier:
            out["tier"] = self.tier
        return out

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Component":
        prov = payload.get("provenance")
        return cls(
            name=str(payload["name"]),
            path=str(payload["path"]),
            bytes=int(payload["bytes"]),
            sha256=str(payload["sha256"]),
            provenance=Provenance.from_dict(prov) if prov else None,
            tier=(str(payload["tier"]) if payload.get("tier") else None),
        )

    @classmethod
    def from_file(cls, pack_root: Path, rel_path: str, name: str, *, provenance: Provenance | None = None, tier: str | None = None) -> "Component":
        fp = pack_root / rel_path
        return cls(
            name=name,
            path=rel_path,
            bytes=file_size(fp),
            sha256=sha256_file(fp),
            provenance=provenance,
            tier=tier,
        )


@dataclass
class Manifest:
    tenant: str
    version: str
    form: str  # full | incremental
    as_of: str | None
    built_at: str
    components: list[Component] = field(default_factory=list)
    data_tiers: dict[str, Any] | None = None
    guards: dict[str, Any] | None = None
    bundle_id: str = ""

    def __post_init__(self) -> None:
        if not self.bundle_id:
            self.bundle_id = bundle_id(self.tenant, self.version, form=self.form, as_of=self.as_of)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MANIFEST_SCHEMA,
            "bundle": {
                "id": self.bundle_id,
                "tenant": self.tenant,
                "version": self.version,
                "form": self.form,
                "as_of": self.as_of,
                "built_at": self.built_at,
                "content_digest": self.content_digest(),
            },
            "components": [c.to_dict() for c in self.components],
            "data_tiers": self.data_tiers,
            "guards": self.guards,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Manifest":
        if payload.get("schema") != MANIFEST_SCHEMA:
            from .errors import ManifestError

            raise ManifestError(f"unsupported manifest schema: {payload.get('schema')!r}")
        bundle = payload.get("bundle") or {}
        return cls(
            tenant=str(bundle["tenant"]),
            version=str(bundle["version"]),
            form=str(bundle["form"]),
            as_of=(str(bundle["as_of"]) if bundle.get("as_of") else None),
            built_at=str(bundle.get("built_at") or ""),
            components=[Component.from_dict(c) for c in payload.get("components") or []],
            data_tiers=payload.get("data_tiers"),
            guards=payload.get("guards"),
            bundle_id=str(bundle.get("id") or ""),
        )

    def component(self, name: str) -> Component | None:
        return next((c for c in self.components if c.name == name), None)

    def content_digest(self) -> str:
        return content_digest(self.components)


def content_digest(components: list[Component]) -> str:
    payload = sorted(
        [{"name": c.name, "bytes": c.bytes, "sha256": c.sha256} for c in components],
        key=lambda item: item["name"],
    )
    return sha256_bytes(canonical_json(payload).encode())


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_manifest(pack_dir: Path, manifest: Manifest) -> Path:
    path = pack_dir / MANIFEST_NAME
    path.write_text(canonical_json(manifest.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def read_manifest(pack_dir: Path) -> Manifest:
    payload = json.loads((pack_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    return Manifest.from_dict(payload)


def write_digest_sidecar(pack_dir: Path) -> Path:
    path = pack_dir / DIGEST_SIDECAR
    path.write_text(sha256_file(pack_dir / PACK_FILENAME) + "\n", encoding="utf-8")
    return path


def read_digest_sidecar(pack_dir: Path) -> str | None:
    path = pack_dir / DIGEST_SIDECAR
    return path.read_text(encoding="utf-8").strip() if path.is_file() else None


def build_pack_tar(pack_dir: Path) -> Path:
    """整包 tar（可复现：排序+固定时间戳+无 gzip 依赖 tar 本体）。"""
    tar_path = pack_dir / PACK_FILENAME
    files = sorted(p for p in pack_dir.rglob("*") if p.is_file() and p != tar_path)
    with tarfile.open(tar_path, "w") as tf:
        for fp in files:
            info = tf.gettarinfo(fp, arcname=str(fp.relative_to(pack_dir)))
            info.mtime = 0
            info.uid, info.gid = 0, 0
            info.uname = info.gname = ""
            with open(fp, "rb") as fh:
                tf.addfile(info, fh)
    return tar_path
