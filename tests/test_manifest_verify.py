"""构建+校验闭环（1.1 骨架 + 4.1 客户侧自校验入口）。"""

from __future__ import annotations

from appliance_packer.cli import main
from appliance_packer.manifest import read_manifest


def _build(tenant_dir, out):
    rc = main(["build", str(tenant_dir), "--out", str(out)])
    assert rc == 0
    return out


def test_build_then_verify_pass(demo_tenant, tmp_path):
    pack = _build(demo_tenant, tmp_path / "pack-v1")
    rc = main(["verify", str(pack)])
    assert rc == 0
    m = read_manifest(pack)
    assert m.bundle_id == "appliance-demo-v1.0.0"
    assert (pack / "pack.tar").is_file() and (pack / "pack.tar.sha256").is_file()
    # 三档快照随包（售前核对口径）
    assert m.data_tiers["included"]["baseline"]["tier"] == "ship_with"
    assert m.guards["packable_guard"]["ok"] is True


def test_tampered_component_fails_verify(demo_tenant, tmp_path):
    pack = _build(demo_tenant, tmp_path / "pack-v1")
    (pack / "content" / "data.json").write_text('{"values": {"CN": 999}}', encoding="utf-8")
    assert main(["verify", str(pack)]) == 1


def test_missing_component_fails_verify(demo_tenant, tmp_path):
    pack = _build(demo_tenant, tmp_path / "pack-v1")
    (pack / "content" / "data.json").unlink()
    assert main(["verify", str(pack)]) == 1


def test_build_refuses_cloud_locked(demo_tenant, tmp_path):
    bundle = {
        "tenant": "demo", "version": "1.0.0", "as_of": "2026-11-04",
        "components": [
            {"name": "data-slice", "path": "content/data.json",
             "provenance": {"source": "baseline", "stable_id": "demo.data", "as_of": "2026-11-04"}},
            {"name": "evil-cloud-gateway", "path": "content/evil.json"},
        ],
    }
    import json
    (demo_tenant / "bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
    (demo_tenant / "content" / "evil.json").write_text('{"url": "https://api.openai.com"}', encoding="utf-8")
    assert main(["build", str(demo_tenant), "--out", str(tmp_path / "pack-bad")]) == 2


def test_build_refuses_undeclared_source(demo_tenant, tmp_path):
    import json
    bundle = json.loads((demo_tenant / "bundle.json").read_text(encoding="utf-8"))
    bundle["components"][0]["provenance"]["source"] = "ghost-feed"
    (demo_tenant / "bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
    assert main(["build", str(demo_tenant), "--out", str(tmp_path / "pack-bad")]) == 2
