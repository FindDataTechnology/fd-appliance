"""构建期可私有化守卫（领域无关，spec「可私有化不变量在构建期强制」）。

两道 fail-closed 检查，任一违规即拒绝出包并指名修复方向：

1. **注册表分类**（继承 lex packer 先例）：bundle 组件清单里出现
   ``cloud_locked`` 或未登记组件 = 违规。
2. **公网硬地址扫描**（appliance 泛化新增）：组件声明的 scan_files 文本里
   出现「非内网」主机名 = 违规。内网白名单=RFC1918/链路本地/tailnet 100.64/10/
   localhost/``.svc``/``.cluster.local``/``.local``/``.internal`` + 租户 allow_hosts。

违规信息 SHALL 给出降级/内网化修法（spec 场景「点名该依赖并拒绝出包，给出修法」）。
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .registry import CLOUD_LOCKED, ComponentRegistry

FIX_SUBSTITUTE = "改用包内替代 {substitute!r}（否则违反可私有化不变量 vertical-appliance-delivery）"
FIX_REMOVE = "从 bundle 组件清单移除（该组件无可打包替代，客户机房不可用）"
FIX_CLASSIFY = "在组件注册表登记其可打包分类（packable|cloud_locked）后再构建"
FIX_INTRANET = "改为内网化端点（{host}→内网服务/随包数据），或把该能力标为「在线增量/客户自采」档并走增量通道"

# http(s)://host 与裸 host 形式（含常见云厂商域名后缀）
_URL_RE = re.compile(r"https?://([^\s\"'<>{}|\\^`\[\]]+)", re.I)
_CLOUD_SUFFIXES = (
    ".amazonaws.com", ".aliyuncs.com", ".azure.com", ".googleapis.com",
    ".tencentyun.com", ".qcloud.com", ".huaweicloud.com", ".openai.com",
    ".huggingface.co", ".anthropic.com", ".githubusercontent.com", ".github.com",
)


@dataclass
class GuardReport:
    checked: list[dict] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict:
        return {"ok": self.ok, "checked": self.checked, "violations": self.violations}


def _is_internal_host(host: str, allow: set[str]) -> bool:
    host = host.split(":")[0].strip(".").lower()
    if not host:
        return True
    if host in allow or any(host == a or host.endswith("." + a) for a in allow):
        return True
    if host in ("localhost",) or host.endswith((".local", ".internal", ".svc", ".cluster.local")):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        pass
    # tailnet CGNAT 100.64.0.0/10 视作内网
    try:
        return ipaddress.ip_address(host) in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return False


def _scan_text(text: str, allow: set[str]) -> list[str]:
    """返回文本中命中的公网硬依赖主机名（去重保序）。"""
    found: list[str] = []
    for m in _URL_RE.finditer(text):
        netloc = m.group(1)
        host = urlparse("http://" + netloc).hostname or ""
        if not host:
            continue
        if host.lower().endswith(_CLOUD_SUFFIXES) or not _is_internal_host(host, allow):
            if host not in found:
                found.append(host)
    return found


def check_bundle(
    registry: ComponentRegistry,
    component_names: list[str],
    tenant_dir: Path | str,
    *,
    allow_hosts: list[str] | None = None,
) -> GuardReport:
    """校验 bundle 组件清单：分类 + 公网硬地址扫描。返回报告（不抛，便于 CLI 汇总）。"""
    allow = {h.lower() for h in (allow_hosts or [])}
    root = Path(tenant_dir)
    report = GuardReport()
    for name in component_names:
        try:
            spec = registry.require(name)
        except KeyError:
            report.violations.append(f"未登记组件 {name!r}：无法判定是否可打包；修复方向：{FIX_CLASSIFY}")
            report.checked.append({"name": name, "class": "unregistered", "ok": False})
            continue
        if spec.klass == CLOUD_LOCKED:
            fix = FIX_SUBSTITUTE.format(substitute=spec.substitute) if spec.substitute else FIX_REMOVE
            report.violations.append(f"云端专属依赖组件 {name!r}（用途：{spec.note or spec.kind}）无法打包；修复方向：{fix}")
            report.checked.append({"name": name, "class": spec.klass, "ok": False})
            continue
        # 公网硬地址扫描
        hits: list[str] = []
        for rel in spec.scan_files or []:
            fp = root / rel
            if not fp.is_file():
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for host in _scan_text(text, allow):
                if host not in hits:
                    hits.append(host)
        if hits:
            report.violations.append(
                f"组件 {name!r} 含公网硬依赖 {hits}；修复方向：{FIX_INTRANET.format(host=hits[0])}"
            )
            report.checked.append({"name": name, "class": spec.klass, "ok": False, "public_hosts": hits})
        else:
            report.checked.append({"name": name, "class": spec.klass, "ok": True})
    return report


def assert_packable(
    registry: ComponentRegistry,
    component_names: list[str],
    tenant_dir: Path | str,
    *,
    allow_hosts: list[str] | None = None,
) -> GuardReport:
    """守卫硬门：违规即抛 GuardViolationError（指名全部违规与修法）。"""
    from .errors import GuardViolationError

    report = check_bundle(registry, component_names, tenant_dir, allow_hosts=allow_hosts)
    if not report.ok:
        raise GuardViolationError("；".join(report.violations), report.violations)
    return report
