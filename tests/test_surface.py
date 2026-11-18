"""产品面判据：只含服务与资产的交付包必须判红，补上宿主后判绿。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from appliance_packer.surface import check_minimal_form, check_product_surface

REGISTRY = {
    "components": [
        {"name": "data-slice", "kind": "data", "class": "packable", "scan_files": ["content/data.json"]},
        {"name": "ledger", "kind": "service", "class": "packable"},
        {"name": "postgres", "kind": "service", "class": "packable"},
        {"name": "paas", "kind": "product", "class": "packable"},
        {"name": "cloud-llm", "kind": "llm", "class": "cloud_locked",
         "substitute": "客户内网网关", "note": "公网 SaaS"},
    ],
    "minimal_form": {
        "required": [
            {"name": "postgres"},
            {"name": "paas"},
            {"name": "ledger"},
            {"name": "dsh-runtime", "provided_by": "paas"},
        ],
        "optional": [{"name": "data-slice", "when": "需要基线切片时"}],
        "cloud_locked": [{"name": "cloud-llm", "degrades_to": "断网时对话不可用，数据面照常"}],
        "product_surface": {"component": "paas"},
    },
}


def _tenant(root: Path, bundle_names: list[str], registry: dict | None = None) -> Path:
    (root / "content").mkdir(parents=True, exist_ok=True)
    (root / "components.json").write_text(json.dumps(registry or REGISTRY, ensure_ascii=False), encoding="utf-8")
    (root / "bundle.json").write_text(json.dumps({
        "tenant": "demo", "version": "1.0.0",
        "components": [{"name": n, "path": "content/data.json"} for n in bundle_names],
    }), encoding="utf-8")
    return root


def test_assets_only_pack_is_red(tmp_path):
    """只含服务与资产 = 不构成可交付产品（spec 第一条场景）。"""
    root = _tenant(tmp_path, ["data-slice", "ledger"])
    report = check_product_surface(root)
    assert not report.ok
    assert any("可登录的产品面" in v for v in report.violations)
    assert any("postgres" in v and "paas" in v for v in report.violations)


def test_pack_with_host_is_green(tmp_path):
    root = _tenant(tmp_path, ["data-slice", "ledger", "postgres", "paas"])
    assert check_product_surface(root).ok, check_product_surface(root).violations


def test_provided_by_counts_as_present(tmp_path):
    """dsh 运行时随 paas 镜像，不单独入包也不算缺。"""
    root = _tenant(tmp_path, ["ledger", "postgres", "paas"])
    report = check_product_surface(root)
    assert report.ok, report.violations
    assert "dsh-runtime" in report.present


def test_minimal_form_must_resolve_against_registry(tmp_path):
    bad = json.loads(json.dumps(REGISTRY))
    bad["minimal_form"]["required"].append({"name": "ghost", "provided_by": "nobody"})
    root = _tenant(tmp_path, ["ledger", "postgres", "paas"], registry=bad)
    violations = check_minimal_form(root)
    assert any("ghost" in v for v in violations)


def test_cloud_locked_needs_degrade_statement(tmp_path):
    bad = json.loads(json.dumps(REGISTRY))
    bad["minimal_form"]["cloud_locked"] = [{"name": "cloud-llm"}]
    root = _tenant(tmp_path, ["ledger", "postgres", "paas"], registry=bad)
    assert any("degrades_to" in v for v in check_minimal_form(root))


def test_unregistered_optional_needs_when(tmp_path):
    bad = json.loads(json.dumps(REGISTRY))
    bad["minimal_form"]["optional"] = [{"name": "data-slice"}]
    root = _tenant(tmp_path, ["ledger", "postgres", "paas"], registry=bad)
    assert any("when" in v for v in check_minimal_form(root))


@pytest.mark.parametrize("tenant", ["erp", "crossborder"])
def test_real_tenants_are_red_today(tenant):
    """真实租户此刻只有服务与资产，判据必须判红——这是判据能红的证明本身。"""
    root = Path(__file__).resolve().parents[1] / "tenants" / tenant
    if not root.is_dir():
        pytest.skip(f"tenant {tenant} not present")
    report = check_product_surface(root)
    assert not report.ok
    assert any("可登录的产品面" in v for v in report.violations)
