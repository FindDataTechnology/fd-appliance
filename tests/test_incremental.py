"""增量通道演练（3.1：拒样回退+现场保原版本；成功样本同源核对等价）。"""

from __future__ import annotations

import json
import shutil

import pytest

from appliance_packer.cli import main
from appliance_packer.errors import ApplyError
from appliance_packer.incremental import (
    apply_incremental,
    build_incremental,
    diff_manifests,
    verify_offline_equivalence,
)
from appliance_packer.manifest import read_manifest


@pytest.fixture
def packs(demo_tenant, demo_tenant_v2, tmp_path):
    v1 = tmp_path / "full-v1"
    v2 = tmp_path / "full-v2"
    assert main(["build", str(demo_tenant), "--out", str(v1)]) == 0
    assert main(["build", str(demo_tenant_v2), "--out", str(v2)]) == 0
    return v1, v2


def test_diff_ops(packs):
    v1, v2 = packs
    deltas = diff_manifests(read_manifest(v1), read_manifest(v2))
    ops = {d.name: d.op for d in deltas}
    assert ops == {"data-slice": "update", "extra-cfg": "add", "fleet-cfg": "delete"}


def test_incremental_apply_equivalence(packs, tmp_path):
    v1, v2 = packs
    inc = tmp_path / "inc-2026-11-05"
    assert main(["incremental", str(v1), str(v2), "--out", str(inc), "--as-of", "2026-11-05"]) == 0
    assert read_manifest(inc).bundle_id == "appliance-demo-v1.1.0-inc-2026-11-05"

    installed = tmp_path / "installed"
    shutil.copytree(v1, installed)
    assert main(["apply", str(installed), str(inc)]) == 0
    assert read_manifest(installed).bundle_id == "appliance-demo-v1.1.0"
    result = main(["equivalence", str(installed), str(v2)])
    assert result == 0
    eq = verify_offline_equivalence(installed, v2)
    assert eq["ok"] and not eq["missing"] and not eq["extra"] and not eq["mismatch"]
    # 应用后的现场文件与目标全量逐字节一致
    assert (installed / "content" / "data.json").read_text(encoding="utf-8") == \
        (v2 / "content" / "data.json").read_text(encoding="utf-8")
    assert not (installed / "content" / "fleet.json").exists()  # delete 落地


def test_corrupted_delta_rejected_base_preserved(packs, tmp_path):
    v1, v2 = packs
    inc = tmp_path / "inc"
    build_incremental(v1, v2, inc, as_of="2026-11-05")
    # 篡改增量包内载荷（模拟传输损坏）
    (inc / "content" / "data.json").write_text('{"values": {"CN": 666}}', encoding="utf-8")

    installed = tmp_path / "installed"
    shutil.copytree(v1, installed)
    before = (installed / "manifest.json").read_bytes()
    with pytest.raises(ApplyError, match="sha256 不符"):
        apply_incremental(installed, inc)
    # 现场保持原版本，不留半更新态
    assert (installed / "manifest.json").read_bytes() == before
    assert read_manifest(installed).bundle_id == "appliance-demo-v1.0.0"
    assert "999" not in (installed / "content" / "data.json").read_text(encoding="utf-8")
    assert (installed / "content" / "fleet.json").exists()  # delete 未落地


def test_wrong_base_refused(packs, tmp_path):
    v1, v2 = packs
    inc = tmp_path / "inc"
    build_incremental(v1, v2, inc, as_of="2026-11-05")
    other = tmp_path / "other-base"
    shutil.copytree(v1, other)
    # 现场 manifest 换成别的版本（模拟错装基座）
    m = read_manifest(other)
    m.version = "9.9.9"
    m.bundle_id = ""
    from appliance_packer.manifest import write_manifest
    write_manifest(other, m)
    with pytest.raises(ApplyError, match="基座不匹配"):
        apply_incremental(other, inc)


def test_no_delta_refused(packs, tmp_path):
    v1, _ = packs
    same = tmp_path / "same"
    shutil.copytree(v1, same)
    with pytest.raises(ValueError, match="different version"):
        build_incremental(v1, same, tmp_path / "inc-x", as_of="2026-11-05")
