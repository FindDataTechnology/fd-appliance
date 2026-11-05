"""包校验（构建侧+客户侧同一入口）：manifest 全过 + 逐组件 sha256 + 门记录复核。

校验项（spec「manifest sha256 全验」+「未声明档位不出包」的验包侧对应）：
1. bundle 字段齐全（id/tenant/version/form/built_at/content_digest）；
2. content_digest 与组件清单重算一致；
3. 组件文件存在、bytes 与 sha256 与 manifest 完全一致；
4. 数据组件带 provenance（source/stable_id/as_of）与档位；
5. guards 记录 ok 且 violations 为空（构建期守卫结果随包自证）；
6. data_tiers 覆盖全部数据组件引用的源；
7. 若存在 pack.tar：sidecar 摘要与重算一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .hashing import sha256_file
from .manifest import (
    DIGEST_SIDECAR,
    Manifest,
    PACK_FILENAME,
    read_digest_sidecar,
    read_manifest,
)
from .version import parse_bundle_id


@dataclass
class VerifyReport:
    pack_dir: str
    bundle_id: str | None = None
    ok: bool = True
    checks: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append({"check": name, "ok": passed, "detail": detail})
        if not passed:
            self.ok = False
            self.errors.append(f"{name}: {detail}" if detail else name)

    def to_dict(self) -> dict:
        return {"pack_dir": self.pack_dir, "bundle_id": self.bundle_id, "ok": self.ok,
                "checks": self.checks, "errors": self.errors}


def verify_pack_dir(pack_dir: Path | str) -> VerifyReport:
    root = Path(pack_dir)
    report = VerifyReport(pack_dir=str(root))
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        report.add("manifest.exists", False, f"{manifest_path} 不存在")
        return report
    try:
        manifest = read_manifest(root)
    except Exception as exc:  # noqa: BLE001 校验器把解析错误转成报告
        report.add("manifest.parse", False, str(exc))
        return report

    bundle = manifest.to_dict()["bundle"]
    report.bundle_id = str(bundle.get("id") or "")
    try:
        parsed = parse_bundle_id(report.bundle_id)
        report.add("bundle.id", True, f"tenant={parsed['tenant']} version={parsed['version']} form={parsed['form']}")
    except ValueError as exc:
        report.add("bundle.id", False, str(exc))

    for key in ("version", "form", "built_at", "content_digest"):
        report.add(f"bundle.{key}", bool(bundle.get(key)), f"value={bundle.get(key)!r}")

    if bundle.get("content_digest"):
        recomputed = manifest.content_digest()
        report.add("bundle.content_digest", recomputed == bundle["content_digest"],
                   f"manifest={bundle['content_digest'][:16]}… recomputed={recomputed[:16]}…")

    if not manifest.components:
        report.add("components.present", False, "manifest 无任何组件")

    referenced_sources: set[str] = set()
    for component in manifest.components:
        prefix = f"component.{component.name}"
        path = root / component.path
        if not path.is_file():
            report.add(f"{prefix}.exists", False, f"{component.path} 缺失")
            continue
        report.add(f"{prefix}.bytes", path.stat().st_size == component.bytes,
                   f"manifest={component.bytes} actual={path.stat().st_size}")
        actual = sha256_file(path)
        report.add(f"{prefix}.sha256", actual == component.sha256,
                   f"manifest={component.sha256[:16]}… actual={actual[:16]}…")
        if component.provenance:
            referenced_sources.add(component.provenance.source)
            report.add(
                f"{prefix}.provenance",
                bool(component.provenance.source and component.provenance.stable_id and component.provenance.as_of),
                component.provenance.to_dict().__repr__(),
            )

    if manifest.form == "full":
        guard = (manifest.guards or {}).get("packable_guard") or {}
        report.add("guard.violations_empty", bool(guard.get("ok")) and not guard.get("violations"),
                   f"violations={guard.get('violations')}")
    else:
        report.add("guard.incremental_of", bool((manifest.guards or {}).get("incremental_of")),
                   f"incremental_of={(manifest.guards or {}).get('incremental_of')!r}")

    tiers_note = manifest.data_tiers or {}
    included = set((tiers_note.get("included") or {}).keys())
    undeclared = sorted(referenced_sources - included)
    report.add("tiers.declared_all", not undeclared,
               f"数据组件引用源未入档位声明：{undeclared}" if undeclared else f"覆盖 {len(included)} 源")

    tar_path = root / PACK_FILENAME
    if tar_path.is_file():
        sidecar = read_digest_sidecar(root)
        if sidecar is None:
            report.add("pack.sidecar", False, f"{DIGEST_SIDECAR} 缺失")
        else:
            actual = sha256_file(tar_path)
            report.add("pack.sha256", sidecar == actual, f"sidecar={sidecar[:16]}… actual={actual[:16]}…")
    return report
