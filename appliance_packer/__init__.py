"""appliance_packer —— 行业线整机交付包构建器（领域无关，vertical-appliance-delivery）。

四条不变量（openspec/changes/add-crossborder-appliance-pack）：
1. 可私有化：构建期守卫拦公网硬依赖与云端专属组件（guard.py）；
2. 数据三档：随包/在线增量/客户自采逐源声明，未声明不出包（tiers.py）；
3. 版本化增量：基座+增量==目标全量（incremental.py）；
4. 断网可用：包自校验 + provenance 全验（verify.py）。
"""

from .errors import (
    ApplyError,
    ApplianceError,
    GuardViolationError,
    ManifestError,
    TierGateError,
    VerifyError,
)
from .guard import GuardReport, assert_packable, check_bundle
from .manifest import Component, Manifest, Provenance
from .registry import ComponentRegistry, ComponentSpec
from .tiers import SourceTier, load_source_tiers
from .verify import VerifyReport, verify_pack_dir
from .version import bundle_id, parse_bundle_id

__all__ = [
    "ApplianceError", "GuardViolationError", "TierGateError", "ManifestError",
    "VerifyError", "ApplyError",
    "ComponentRegistry", "ComponentSpec", "GuardReport", "check_bundle", "assert_packable",
    "SourceTier", "load_source_tiers",
    "Component", "Manifest", "Provenance",
    "VerifyReport", "verify_pack_dir",
    "bundle_id", "parse_bundle_id",
]
