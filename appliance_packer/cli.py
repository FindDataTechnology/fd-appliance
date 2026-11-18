"""CLI：build / verify / incremental / apply / equivalence。

约定租户目录形态（tenants/<tenant>/）：
    components.json     组件注册表（可打包分类 + scan_files）
    sources-tiers.json  数据源三档声明
    bundle.json         全量包声明：version + 组件清单（name/path/provenance）
    content/            组件文件（path 相对租户目录）

    $ python -m appliance_packer build tenants/crossborder --out /tmp/packs/v1
    $ python -m appliance_packer verify /tmp/packs/v1
    $ python -m appliance_packer incremental <base_pack_dir> <target_pack_dir> --out <inc_dir> --as-of 2026-11-05
    $ python -m appliance_packer apply <installed_dir> <inc_dir>
    $ python -m appliance_packer equivalence <installed_dir> <target_full_dir>
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from .errors import ApplianceError
from .guard import assert_packable
from .incremental import apply_incremental, build_incremental, verify_offline_equivalence
from .manifest import (
    CONTENT_DIR,
    Component,
    Manifest,
    Provenance,
    build_pack_tar,
    now_iso,
    write_digest_sidecar,
    write_manifest,
)
from .manifest_io import load_json
from .install import plan, run_install
from .registry import ComponentRegistry
from .surface import check_minimal_form, check_product_surface
from .tiers import assert_sources_declared, load_source_tiers, tiers_note
from .verify import verify_pack_dir


def _cmd_build(args: argparse.Namespace) -> int:
    tenant_dir = Path(args.tenant_dir)
    bundle = load_json(tenant_dir / "bundle.json")
    registry = ComponentRegistry.load(tenant_dir / "components.json")
    tiers = load_source_tiers(tenant_dir / "sources-tiers.json")

    names = [str(c["name"]) for c in bundle["components"]]
    # 门 1：可私有化守卫（分类 + 公网硬地址）
    guard_report = assert_packable(registry, names, tenant_dir, allow_hosts=bundle.get("allow_hosts"))
    # 门 2：数据三档声明（引用源全部已声明）
    referenced = sorted({
        str(c["provenance"]["source"]) for c in bundle["components"] if c.get("provenance")
    })
    assert_sources_declared(tiers, referenced)

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    (out / CONTENT_DIR).mkdir(parents=True)

    components: list[Component] = []
    for item in bundle["components"]:
        rel_src = str(item["path"])
        fp = tenant_dir / rel_src
        if not fp.is_file():
            raise ApplianceError(f"组件文件缺失：{item['name']} → {rel_src}")
        prov = item.get("provenance")
        tier = tiers[prov["source"]].tier if prov and prov["source"] in tiers else None
        dst_rel = f"{CONTENT_DIR}/{Path(rel_src).name}"
        dst = out / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fp, dst)
        components.append(Component.from_file(
            out, dst_rel, str(item["name"]),
            provenance=Provenance.from_dict(prov) if prov else None,
            tier=tier,
        ))

    manifest = Manifest(
        tenant=bundle["tenant"],
        version=str(bundle["version"]),
        form="full",
        as_of=(str(bundle["as_of"]) if bundle.get("as_of") else None),
        built_at=now_iso(),
        components=sorted(components, key=lambda c: c.name),
        data_tiers=tiers_note(tiers, referenced),
        guards={"packable_guard": guard_report.to_dict()},
    )
    write_manifest(out, manifest)
    build_pack_tar(out)
    write_digest_sidecar(out)

    report = verify_pack_dir(out)
    if not report.ok:
        print(f"出包后自校验失败：{report.errors}", file=sys.stderr)
        return 1
    print(f"BUILT {manifest.bundle_id}  components={len(components)}  digest={manifest.content_digest()[:16]}…")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    report = verify_pack_dir(Path(args.pack_dir))
    for check in report.checks:
        mark = "ok " if check["ok"] else "FAIL"
        print(f"[{mark}] {check['check']}  {check['detail']}")
    print(("VERIFY PASS " if report.ok else "VERIFY FAIL ") + report.bundle_id)
    return 0 if report.ok else 1


def _cmd_incremental(args: argparse.Namespace) -> int:
    out = build_incremental(Path(args.base), Path(args.target), Path(args.out), as_of=args.as_of)
    inc = Manifest.from_dict(load_json(out / "manifest.json"))
    print(f"INCREMENTAL BUILT {inc.bundle_id}  ops={len(inc.guards.get('delta_ops', []))}  → {out}")
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    applied = apply_incremental(Path(args.installed), Path(args.incremental))
    print(f"APPLIED → {applied.bundle_id}  components={len(applied.components)}")
    return 0


def _cmd_equivalence(args: argparse.Namespace) -> int:
    result = verify_offline_equivalence(Path(args.installed), Path(args.target_full))
    if result["ok"]:
        print(f"EQUIVALENCE PASS  digest={result['applied_digest'][:16]}…")
        return 0
    print(f"EQUIVALENCE FAIL  missing={result['missing']} extra={result['extra']} mismatch={result['mismatch']}")
    return 1


def _cmd_surface(args: argparse.Namespace) -> int:
    """售前/构建期判据：交付包是否构成可用的产品（含可登录产品面 + 必需项齐）。"""
    tenant_dir = Path(args.tenant_dir)
    form = check_minimal_form(tenant_dir)
    report = check_product_surface(tenant_dir)
    for name in report.present:
        print(f"[ok ] required  {name}")
    for name in report.required:
        if name not in report.present:
            print(f"[MISS] required  {name}")
    for v in form + report.violations:
        print(f"[FAIL] {v}")
    if form or not report.ok:
        print(f"SURFACE REFUSED {report.tenant}")
        return 2
    print(f"SURFACE PASS {report.tenant} (product surface: {report.present})")
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    steps = plan()
    if args.dry_run:
        for index, step in enumerate(steps, start=1):
            print(f"[{index}/{len(steps)}] {step.name}: {step.command}")
        return 0
    return 0 if run_install(steps) == 0 else 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="appliance_packer", description="行业线整机交付包构建器")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="构建全量包（守卫+三档门+自校验）")
    b.add_argument("tenant_dir"); b.add_argument("--out", required=True)
    b.set_defaults(fn=_cmd_build)

    v = sub.add_parser("verify", help="包校验（客户侧同一入口）")
    v.add_argument("pack_dir")
    v.set_defaults(fn=_cmd_verify)

    i = sub.add_parser("incremental", help="base→target 增量包")
    i.add_argument("base"); i.add_argument("target"); i.add_argument("--out", required=True); i.add_argument("--as-of", required=True)
    i.set_defaults(fn=_cmd_incremental)

    a = sub.add_parser("apply", help="现场应用增量（校验不过即拒绝，保持原版本）")
    a.add_argument("installed"); a.add_argument("incremental")
    a.set_defaults(fn=_cmd_apply)

    e = sub.add_parser("equivalence", help="同源核对：base+增量 == 目标全量")
    e.add_argument("installed"); e.add_argument("target_full")
    e.set_defaults(fn=_cmd_equivalence)

    i2 = sub.add_parser("install", help="装机编排：PG 就绪→migrate→种子→paas→健康检查（失败点名中止）")
    i2.add_argument("--dry-run", action="store_true", help="只打印步骤与命令，不执行")
    i2.set_defaults(fn=_cmd_install)

    s = sub.add_parser("surface", help="判据：交付包是否构成可用的产品（含可登录产品面）")
    s.add_argument("tenant_dir")
    s.set_defaults(fn=_cmd_surface)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except ApplianceError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
