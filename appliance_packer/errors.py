"""appliance_packer 异常口径：违规必须指名组件/依赖与修复方向（fail loud）。"""


class ApplianceError(Exception):
    """基类：所有出包拒绝都携带可打印的 violations。"""

    def __init__(self, message: str, violations: list[str] | None = None):
        super().__init__(message)
        self.violations = violations or [message]


class GuardViolationError(ApplianceError):
    """可私有化不变量违规：云端专属依赖/公网硬地址/未登记组件。"""


class TierGateError(ApplianceError):
    """数据三档门违规：源未声明档位/档位未知 → 拒绝出包。"""


class ManifestError(ApplianceError):
    """manifest schema/摘要不合法。"""


class VerifyError(ApplianceError):
    """包校验失败（字节数/sha256/provenance/门记录任一不符）。"""


class ApplyError(ApplianceError):
    """增量应用被拒：现场保持原版本，不留半更新态。"""
