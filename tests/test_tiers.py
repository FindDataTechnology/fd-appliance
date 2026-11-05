"""三档声明门实证（2.1「未声明档位拒绝出包」）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from appliance_packer.errors import TierGateError
from appliance_packer.tiers import (
    CUSTOMER_COLLECTS,
    ONLINE_INCREMENT,
    SHIP_WITH,
    assert_sources_declared,
    load_source_tiers,
    tiers_note,
)


def test_tiers_load(demo_tenant):
    tiers = load_source_tiers(demo_tenant / "sources-tiers.json")
    assert tiers["baseline"].tier == SHIP_WITH
    assert tiers["live-feed"].tier == ONLINE_INCREMENT
    assert tiers["merchant"].tier == CUSTOMER_COLLECTS


def test_undeclared_source_refused(demo_tenant):
    tiers = load_source_tiers(demo_tenant / "sources-tiers.json")
    with pytest.raises(TierGateError) as exc:
        assert_sources_declared(tiers, ["baseline", "ghost-feed"])
    assert "ghost-feed" in str(exc.value)


def test_unknown_tier_rejected(tmp_path: Path):
    p = tmp_path / "st.json"
    p.write_text(json.dumps({"sources": [
        {"source": "x", "tier": "maybe_ship", "offline_availability": "?"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="maybe_ship"):
        load_source_tiers(p)


def test_missing_offline_availability_rejected(tmp_path: Path):
    p = tmp_path / "st.json"
    p.write_text(json.dumps({"sources": [{"source": "x", "tier": "ship_with"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="offline_availability"):
        load_source_tiers(p)


def test_tiers_note_snapshots_included(demo_tenant):
    tiers = load_source_tiers(demo_tenant / "sources-tiers.json")
    note = tiers_note(tiers, ["baseline", "live-feed"])
    assert set(note["included"]) == {"baseline", "live-feed"}
    assert "merchant" not in note["included"]  # 未引用的源不进本包快照
    assert note["included"]["live-feed"]["update_mode"] == "增量包"
