"""守卫实证（1.1「假组件实证被拦」+ spec「可私有化不变量在构建期强制」）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from appliance_packer.errors import GuardViolationError
from appliance_packer.guard import _scan_text, assert_packable, check_bundle
from appliance_packer.registry import ComponentRegistry


def _registry(tenant_dir: Path) -> ComponentRegistry:
    return ComponentRegistry.load(tenant_dir / "components.json")


def test_cloud_locked_component_rejected(demo_tenant):
    with pytest.raises(GuardViolationError) as exc:
        assert_packable(_registry(demo_tenant), ["data-slice", "evil-cloud-gateway"], demo_tenant)
    msg = str(exc.value)
    assert "evil-cloud-gateway" in msg
    assert "客户内网 LLM 网关" in msg  # 修复方向点名替代件


def test_public_hard_address_rejected(demo_tenant):
    report = check_bundle(_registry(demo_tenant), ["leaky-cfg"], demo_tenant)
    assert not report.ok
    assert any("api.openai.com" in v for v in report.violations)
    assert any("内网化" in v for v in report.violations)  # 给出修法


def test_unregistered_component_rejected(demo_tenant):
    with pytest.raises(GuardViolationError, match="ghost-component"):
        assert_packable(_registry(demo_tenant), ["ghost-component"], demo_tenant)


def test_internal_hosts_pass(demo_tenant):
    # leaky.json 里的 platform.ns.svc 内网端点不触发违规，只有 api.openai.com 触发
    report = check_bundle(_registry(demo_tenant), ["leaky-cfg"], demo_tenant)
    assert not any("platform.ns.svc" in v for v in report.violations)


def test_allow_hosts_override(tmp_path):
    root = tmp_path / "t"
    (root / "content").mkdir(parents=True)
    (root / "content" / "a.json").write_text('{"u": "https://tenant-partner.example.com/api"}', encoding="utf-8")
    (root / "components.json").write_text(json.dumps({"components": [
        {"name": "a", "kind": "config", "class": "packable", "scan_files": ["content/a.json"]}]}), encoding="utf-8")
    reg = ComponentRegistry.load(root / "components.json")
    assert not check_bundle(reg, ["a"], root).ok
    assert check_bundle(reg, ["a"], root, allow_hosts=["tenant-partner.example.com"]).ok


def test_clean_bundle_passes(demo_tenant):
    report = assert_packable(_registry(demo_tenant), ["data-slice", "fleet-cfg"], demo_tenant)
    assert report.ok


def test_bare_host_without_scheme_is_scanned():
    # .env 最常见的写法没有 scheme：守卫承诺覆盖裸 host，这条用例锁住该不变量
    assert _scan_text("OPENAI_BASE=api.openai.com", set()) == ["api.openai.com"]
    assert _scan_text('OPENAI_BASE="api.openai.com:443/v1"', set()) == ["api.openai.com"]


def test_internal_hosts_not_flagged():
    # 同命名空间裸服务名 / tailnet CGNAT / 链路本地都不该被当成公网
    assert _scan_text("DB=http://postgres:5432", set()) == []
    assert _scan_text("DB=postgres:5432", set()) == []
    assert _scan_text("TAILNET=http://100.64.1.5:8080", set()) == []
    assert _scan_text("META=http://169.254.169.254/latest", set()) == []


def test_identifier_shapes_not_flagged():
    # 版本号 / 文件名 / 日期不是主机名，误报会逼人放宽 allow_hosts
    for text in ("VERSION=v1.2.3", "LOG=app.json", "AS_OF=2026-11", "CONFIG=/etc/app.json"):
        assert _scan_text(text, set()) == [], text


def test_allow_hosts_still_overrides_bare_host():
    assert _scan_text("PARTNER=tenant-partner.example.com", {"tenant-partner.example.com"}) == []
