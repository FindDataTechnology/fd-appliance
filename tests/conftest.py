"""测试工厂：构造假租户目录（含云端专属组件与公网硬依赖组件，实证守卫拦截）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

COMPONENTS = {
    "components": [
        {"name": "data-slice", "kind": "data", "class": "packable", "scan_files": ["content/data.json"]},
        {"name": "fleet-cfg", "kind": "fleet", "class": "packable", "scan_files": ["content/fleet.json"]},
        {"name": "evil-cloud-gateway", "kind": "llm", "class": "cloud_locked",
         "substitute": "客户内网 LLM 网关", "note": "公网大模型网关"},
        {"name": "leaky-cfg", "kind": "config", "class": "packable", "scan_files": ["content/leaky.json"]},
    ]
}

TIERS = {
    "sources": [
        {"source": "baseline", "tier": "ship_with", "offline_availability": "随包基线，断网可用"},
        {"source": "live-feed", "tier": "online_increment", "offline_availability": "基线随包，更新需出网",
         "update_mode": "增量包"},
        {"source": "merchant", "tier": "customer_collects", "offline_availability": "客户授权自采"},
    ]
}

DATA_V1 = {"values": {"CN": 1, "JP": 3}, "as_of": "2026-10"}
DATA_V2 = {"values": {"CN": 1, "JP": 3, "AU": 11}, "as_of": "2026-10"}
FLEET = {"base_url": "{{APPLIANCE_YIZUO_BASE}}", "template": "demo"}
LEAKY = {"endpoint": "https://api.openai.com/v1/chat", "fallback": "http://platform.ns.svc:3100"}


def _bundle(tenant_dir: Path, version: str, names: list[str]) -> None:
    components = []
    for name in names:
        entry = {"name": name, "path": {"data-slice": "content/data.json",
                                        "fleet-cfg": "content/fleet.json",
                                        "leaky-cfg": "content/leaky.json",
                                        "evil-cloud-gateway": "content/evil.json"}[name]}
        if name == "data-slice":
            entry["provenance"] = {"source": "baseline", "stable_id": "demo.data", "as_of": "2026-11-04"}
        components.append(entry)
    (tenant_dir / "bundle.json").write_text(json.dumps(
        {"tenant": "demo", "version": version, "as_of": "2026-11-04", "components": components},
        ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture
def demo_tenant(tmp_path: Path) -> Path:
    root = tmp_path / "tenant-demo"
    (root / "content").mkdir(parents=True)
    (root / "components.json").write_text(json.dumps(COMPONENTS, ensure_ascii=False), encoding="utf-8")
    (root / "sources-tiers.json").write_text(json.dumps(TIERS, ensure_ascii=False), encoding="utf-8")
    (root / "content" / "data.json").write_text(json.dumps(DATA_V1), encoding="utf-8")
    (root / "content" / "fleet.json").write_text(json.dumps(FLEET), encoding="utf-8")
    (root / "content" / "leaky.json").write_text(json.dumps(LEAKY), encoding="utf-8")
    _bundle(root, "1.0.0", ["data-slice", "fleet-cfg"])
    return root


@pytest.fixture
def demo_tenant_v2(tmp_path: Path) -> Path:
    root = tmp_path / "tenant-demo-v2"
    (root / "content").mkdir(parents=True)
    (root / "components.json").write_text(json.dumps(COMPONENTS, ensure_ascii=False), encoding="utf-8")
    (root / "sources-tiers.json").write_text(json.dumps(TIERS, ensure_ascii=False), encoding="utf-8")
    (root / "content" / "data.json").write_text(json.dumps(DATA_V2), encoding="utf-8")
    (root / "content" / "fleet.json").write_text(json.dumps(FLEET), encoding="utf-8")
    (root / "content" / "extra.json").write_text('{"new": true}', encoding="utf-8")
    bundle = {"tenant": "demo", "version": "1.1.0", "as_of": "2026-11-05", "components": [
        {"name": "data-slice", "path": "content/data.json",
         "provenance": {"source": "baseline", "stable_id": "demo.data", "as_of": "2026-11-05"}},
        {"name": "extra-cfg", "path": "content/extra.json"},
    ]}
    # extra-cfg 需登记：补进注册表
    comps = json.loads((root / "components.json").read_text(encoding="utf-8"))
    comps["components"].append({"name": "extra-cfg", "kind": "config", "class": "packable"})
    (root / "components.json").write_text(json.dumps(comps, ensure_ascii=False), encoding="utf-8")
    (root / "bundle.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return root
