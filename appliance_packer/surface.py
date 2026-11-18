"""交付包「含可登录产品面」判据 + 最小可用形态核对。

spec：``vertical-appliance-delivery``「交付包必须构成一个可用的产品」——
只含 MCP 服务、数据种子与 pack 资产的包 MUST NOT 被宣称为可交付产品。

判据对象是**交付包（bundle.json）**，不是组件注册表：登记不代表包里有。
所以这个门在出包前跑一次，判红时点名的必须是「包里缺的那一项」。

最小可用形态（``components.json`` 的 ``minimal_form``）同样在构建期核对：
``required`` 里的每一项要么本身就是已登记组件，要么由某项已登记组件提供
（``provided_by``，如 dsh 运行时随 paas 镜像）。对不上的项 = 登记表自相矛盾。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .registry import ComponentRegistry

MISSING_SURFACE = "缺的是「可登录的产品面」（客户能登录/对话/看运行态的宿主），只含服务与资产的包不算产品"


@dataclass
class SurfaceReport:
    tenant: str
    bundle_components: list[str] = field(default_factory=list)
    required: list[str] = field(default_factory=list)
    present: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "tenant": self.tenant,
            "bundle_components": self.bundle_components,
            "required": self.required,
            "present": self.present,
            "violations": self.violations,
        }


def _minimal_form(tenant_dir: Path) -> dict:
    payload = json.loads((tenant_dir / "components.json").read_text(encoding="utf-8"))
    return payload.get("minimal_form") or {}


def check_minimal_form(tenant_dir: Path | str) -> list[str]:
    """登记表自洽：required 每项可解析到已登记组件（自身或 provided_by）。"""
    root = Path(tenant_dir)
    registry = ComponentRegistry.load(root / "components.json")
    registered = set(registry.names())
    violations: list[str] = []
    mf = _minimal_form(root)
    required = mf.get("required") or []
    if not required:
        violations.append("components.json 未登记最小可用形态（minimal_form.required 为空）：无法判定「够不够交付」")
    for item in required:
        name = str(item.get("name") or "")
        provider = item.get("provided_by")
        if provider:
            if str(provider) not in registered:
                violations.append(f"最小可用形态 required {name!r} 声称由 {provider!r} 提供，但该组件未登记")
        elif name not in registered:
            violations.append(f"最小可用形态 required {name!r} 未在组件注册表登记（也不声明 provided_by）")
    for item in (mf.get("optional") or []):
        if not item.get("when"):
            violations.append(f"可选组件 {item.get('name')!r} 未写适用条件（when）：不得暗示默认已具备")
    locked = registry.names()
    for item in (mf.get("cloud_locked") or []):
        if str(item.get("name")) not in locked:
            violations.append(f"cloud_locked 项 {item.get('name')!r} 未在组件注册表登记")
        if not item.get("degrades_to"):
            violations.append(f"cloud_locked 项 {item.get('name')!r} 未声明断网降级形态（degrades_to）")
    return violations


def check_product_surface(tenant_dir: Path | str) -> SurfaceReport:
    """交付包是否含可登录产品面 + 必需项是否齐。"""
    root = Path(tenant_dir)
    bundle = json.loads((root / "bundle.json").read_text(encoding="utf-8"))
    registry = ComponentRegistry.load(root / "components.json")
    mf = _minimal_form(root)

    report = SurfaceReport(tenant=str(bundle.get("tenant") or root.name))
    report.bundle_components = sorted(str(c["name"]) for c in bundle.get("components") or [])
    report.required = [str(r.get("name")) for r in (mf.get("required") or [])]

    in_bundle = set(report.bundle_components)
    for item in (mf.get("required") or []):
        name = str(item.get("name") or "")
        provider = item.get("provided_by")
        if name in in_bundle or (provider and str(provider) in in_bundle):
            report.present.append(name)

    surface = (mf.get("product_surface") or {}).get("component")
    if not surface:
        report.violations.append("components.json 未声明 product_surface.component：无法判定产品面归属")
    elif str(surface) not in in_bundle:
        report.violations.append(
            f"交付包 {report.tenant}/{bundle.get('version')} 不含产品宿主 {surface!r}：{MISSING_SURFACE}"
        )
    else:
        try:
            registry.require(str(surface))
        except KeyError:
            report.violations.append(f"产品宿主 {surface!r} 未在组件注册表登记")

    missing = [n for n in report.required if n not in report.present]
    if missing:
        report.violations.append(
            "交付包缺最小可用形态的必需项：" + "、".join(missing)
            + "；缺任一必需项交付不成立（minimal_form.required）"
        )
    return report
