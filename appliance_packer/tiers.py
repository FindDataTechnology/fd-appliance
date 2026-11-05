"""数据三档分层与逐源声明（spec「交付物数据三档分层且逐源声明」）。

档位（领域无关口径，泛化 lex 的引用/语料/文书三档为「可得性三档」）：
- ``ship_with``        随包数据：基线切片进全量包，断网即可用；
- ``online_increment`` 在线增量：随包只给基线，更新走增量通道（客户侧需出网或中转）；
- ``customer_collects`` 客户自采：不随包不增量，装后由客户自采/自带凭证（如商家授权内圈数据）。

出包门：bundle 数据切片引用的每个源 SHALL 在 sources-tiers 声明档位与离线可得性；
**未声明档位的源 SHALL NOT 出包**（TierGateError 点名全部未声明源）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

SHIP_WITH = "ship_with"
ONLINE_INCREMENT = "online_increment"
CUSTOMER_COLLECTS = "customer_collects"
TIERS = {SHIP_WITH, ONLINE_INCREMENT, CUSTOMER_COLLECTS}

TIER_LABELS = {
    SHIP_WITH: "随包数据（基线切片入全量包，断网可用）",
    ONLINE_INCREMENT: "在线增量（随包基线+版本化增量包更新）",
    CUSTOMER_COLLECTS: "客户自采（不随包；装后客户自采/自带授权）",
}


@dataclass
class SourceTier:
    source: str
    tier: str
    offline_availability: str  # 离线可得性说明（售前核对口径）
    update_mode: str = ""

    def to_dict(self) -> dict:
        out = {"source": self.source, "tier": self.tier, "offline_availability": self.offline_availability}
        if self.update_mode:
            out["update_mode"] = self.update_mode
        return out


def load_source_tiers(path: Path | str) -> dict[str, SourceTier]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[str, SourceTier] = {}
    for item in payload.get("sources") or []:
        source = str(item["source"])
        tier = str(item["tier"])
        if tier not in TIERS:
            raise ValueError(f"source {source!r}: tier must be {'|'.join(sorted(TIERS))}, got {tier!r}")
        if not item.get("offline_availability"):
            raise ValueError(f"source {source!r}: 缺离线可得性声明（offline_availability）")
        out[source] = SourceTier(
            source=source,
            tier=tier,
            offline_availability=str(item["offline_availability"]),
            update_mode=str(item.get("update_mode") or ""),
        )
    return out


def assert_sources_declared(declared: dict[str, SourceTier], referenced: list[str]) -> None:
    """出包门：bundle 引用的源全部已声明档位，否则拒绝出包（点名未声明者）。"""
    from .errors import TierGateError

    missing = [s for s in referenced if s not in declared]
    if missing:
        raise TierGateError(
            "拒绝出包：以下数据源未声明三档档位（随包/在线增量/客户自采）："
            + "、".join(missing)
            + "；修复方向：在 sources-tiers 逐源补声明 tier 与 offline_availability",
            [f"undeclared source: {s}" for s in missing],
        )


def tiers_note(declared: dict[str, SourceTier], referenced: list[str]) -> dict:
    """manifest.data_tiers：本包收录源的档位快照（售前核对「私有化后可得哪些数据」）。"""
    included = {s: declared[s].to_dict() for s in referenced if s in declared}
    return {
        "labels": TIER_LABELS,
        "included": included,
        "note": "未声明档位的源不出包；按档报价不出现「上线即全量」的含糊承诺（vertical-appliance-delivery）",
    }
