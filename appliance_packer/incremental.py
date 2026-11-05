"""版本化增量包通道（spec「更新走版本化增量通道」）。

等价判定（继承 lex 先例的可测试定义）：
    对基座 full 包应用增量包后，组件集合与逐组件 sha256/bytes
    与目标 full 包完全一致 → 离线整包与在线增量等价。

应用语义（spec 场景「增量包校验不过即回退」）：
    apply 先在 staging 全量校验（delta 清单 sha256 vs 实际文件），
    **任何一项不过 → 抛 ApplyError，现场 base 目录零改动**；
    全过才原子换入。不留半更新态。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ApplyError
from .hashing import sha256_file
from .manifest import (
    CONTENT_DIR,
    Manifest,
    now_iso,
    read_manifest,
    write_manifest,
)
from .manifest_io import dump_json, load_json
from .version import parse_bundle_id


@dataclass
class Delta:
    name: str
    op: str  # add | update | delete
    path: str | None
    bytes: int | None
    sha256: str | None
    base_sha256: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "op": self.op, "path": self.path, "bytes": self.bytes,
                "sha256": self.sha256, "base_sha256": self.base_sha256}


def diff_manifests(base: Manifest, target: Manifest) -> list[Delta]:
    deltas: list[Delta] = []
    base_map = {c.name: c for c in base.components}
    for c in target.components:
        old = base_map.get(c.name)
        if old is None:
            deltas.append(Delta(c.name, "add", c.path, c.bytes, c.sha256, None))
        elif old.sha256 != c.sha256:
            deltas.append(Delta(c.name, "update", c.path, c.bytes, c.sha256, old.sha256))
    for name, old in base_map.items():
        if target.component(name) is None:
            deltas.append(Delta(name, "delete", None, None, None, old.sha256))
    return deltas


def build_incremental(base_dir: Path, target_dir: Path, out_dir: Path, *, as_of: str) -> Path:
    """base→target 的增量包：变更/新增组件文件 + delta.json + manifest。"""
    base = read_manifest(base_dir)
    target = read_manifest(target_dir)
    if base.tenant != target.tenant:
        raise ValueError(f"tenant mismatch: {base.tenant} vs {target.tenant}")
    if parse_bundle_id(base.bundle_id)["version"] == parse_bundle_id(target.bundle_id)["version"] and base.form == target.form:
        raise ValueError("incremental must move to a different version/form than base")
    deltas = diff_manifests(base, target)
    if not deltas:
        raise ValueError("no delta between base and target")

    out = Path(out_dir)
    (out / CONTENT_DIR).mkdir(parents=True, exist_ok=True)
    moved: list[Delta] = []
    for d in deltas:
        if d.op in ("add", "update"):
            src = target_dir / (d.path or "")
            dst = out / (d.path or "")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            moved.append(d)
    dump_json(out / "delta.json", [d.to_dict() for d in deltas])
    inc = Manifest(
        tenant=base.tenant,
        version=parse_bundle_id(target.bundle_id)["version"],
        form="incremental",
        as_of=as_of,
        built_at=now_iso(),
        components=[target.component(d.name) for d in moved if target.component(d.name)],
        data_tiers=target.data_tiers,
        guards={"incremental_of": base.bundle_id, "delta_ops": [d.to_dict() for d in deltas]},
    )
    write_manifest(out, inc)
    return out


def apply_incremental(base_dir: Path, incremental_dir: Path) -> Manifest:
    """先全量校验再原子应用；任何校验不过 → ApplyError 且 base 零改动。"""
    base_dir, inc_dir = Path(base_dir), Path(incremental_dir)
    base = read_manifest(base_dir)
    inc = read_manifest(inc_dir)
    recorded = (inc.guards or {}).get("incremental_of")
    if recorded != base.bundle_id:
        raise ApplyError(f"增量包基座不匹配：包记 {recorded!r}，现场 {base.bundle_id!r}——拒绝应用")
    deltas = load_json(inc_dir / "delta.json")

    # ── 校验阶段（不碰 base）──
    problems: list[str] = []
    for d in deltas:
        if d["op"] == "delete":
            if base.component(d["name"]) is None:
                problems.append(f"delete 目标不存在：{d['name']}")
            continue
        fp = inc_dir / (d["path"] or "")
        if not fp.is_file():
            problems.append(f"缺文件：{d['path']}")
            continue
        if sha256_file(fp) != d["sha256"]:
            problems.append(f"sha256 不符：{d['name']}")
        if fp.stat().st_size != d["bytes"]:
            problems.append(f"bytes 不符：{d['name']}")
        if d["op"] == "update":
            old = base.component(d["name"])
            if old is None or old.sha256 != d["base_sha256"]:
                problems.append(f"update 基座态不符：{d['name']}")
    if problems:
        raise ApplyError("增量包校验不过，现场保持原版本：" + "；".join(problems), problems)

    # ── 应用阶段（校验全过才动 base）──
    components = {c.name: c for c in base.components}
    for d in deltas:
        if d["op"] == "delete":
            old = components.pop(d["name"])
            (base_dir / old.path).unlink(missing_ok=True)
        else:
            src = inc_dir / (d["path"] or "")
            dst = base_dir / (d["path"] or "")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            new_c = inc.component(d["name"])
            if new_c is None:
                raise ApplyError(f"增量 manifest 缺组件记录：{d['name']}")
            components[d["name"]] = new_c
    applied = Manifest(
        tenant=base.tenant,
        version=parse_bundle_id(inc.bundle_id)["version"],
        form="full",
        as_of=None,
        built_at=now_iso(),
        components=sorted(components.values(), key=lambda c: c.name),
        data_tiers=inc.data_tiers or base.data_tiers,
        guards=base.guards,
    )
    write_manifest(base_dir, applied)
    return applied


def verify_offline_equivalence(applied_dir: Path, target_full_dir: Path) -> dict:
    """同源核对：应用增量后的现场与目标全量包逐组件一致。"""
    applied = read_manifest(Path(applied_dir))
    target = read_manifest(Path(target_full_dir))
    a = {c.name: (c.sha256, c.bytes) for c in applied.components}
    t = {c.name: (c.sha256, c.bytes) for c in target.components}
    missing = sorted(set(t) - set(a))
    extra = sorted(set(a) - set(t))
    mismatch = sorted(n for n in set(a) & set(t) if a[n] != t[n])
    return {"ok": not (missing or extra or mismatch), "missing": missing,
            "extra": extra, "mismatch": mismatch,
            "applied_digest": applied.content_digest(), "target_digest": target.content_digest()}
