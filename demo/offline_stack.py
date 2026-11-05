#!/usr/bin/env python3
"""整机包离线栈（客户机房断网形态，stdlib-only）：查数/看板/舰队日报三链路。

用法（容器内 --network none）：
    python offline_stack.py <pack_dir> verify                    # 客户侧包校验
    python offline_stack.py <pack_dir> query policy.notice_count --country CN
    python offline_stack.py <pack_dir> query port.calls
    python offline_stack.py <pack_dir> dashboard --out dashboard.html
    python offline_stack.py <pack_dir> daily-report --out report.md

数据只读包内 content/ 基线切片；在线增量源如实显位（断网不更新+内网替代说明）。
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

# 舰队模板引用的在线增量源（断网显位口径）
ONLINE_NOTE = "在线增量源——断网不更新；装后走版本化增量包通道或内网化端点"


def _iter_json(pack: Path, subdir: str = "content"):
    # 跳过 macOS AppleDouble（._*）等隐藏文件
    return [fp for fp in sorted((pack / subdir).glob("*.json")) if not fp.name.startswith(".")]


def load_slices(pack: Path) -> dict:
    slices = {}
    for fp in _iter_json(pack):
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("concept"):
            slices[payload["concept"]] = payload
    return slices


def load_fleet_templates(pack: Path) -> list[dict]:
    templates = []
    for fp in _iter_json(pack):
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("template"):
            templates.append(payload)
    return templates


def as_of(slices: dict) -> str:
    stamps = [str(v.get("provenance", {}).get("as_of") or "") for v in slices.values()]
    stamps = [s for s in stamps if s]
    return max(stamps) if stamps else "unknown"


def cmd_verify(pack: Path) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from appliance_packer.verify import verify_pack_dir

    report = verify_pack_dir(pack)
    for check in report.checks:
        print(f"[{'ok ' if check['ok'] else 'FAIL'}] {check['check']}  {check['detail']}")
    print(("VERIFY PASS " if report.ok else "VERIFY FAIL ") + str(report.bundle_id))
    return 0 if report.ok else 1


def cmd_query(pack: Path, concept: str, country: str | None) -> int:
    slices = load_slices(pack)
    if concept not in slices:
        print(f"未收录概念：{concept}（随包仅基线切片：{'、'.join(sorted(slices))}）")
        print(ONLINE_NOTE)
        return 1
    s = slices[concept]
    prov = s.get("provenance", {})
    print(f"concept={concept}  as_of={prov.get('as_of')}  verified_by={prov.get('verified_by', '')[:40]}…")
    if concept == "policy.notice_count":
        latest = s.get("latest_month", {})
        print(f"latest_month={latest.get('month')}  by_country={latest.get('by_country')}")
        if country:
            v = latest.get("by_country", {}).get(country)
            print(f"{country} = {v} 通报/月" if v is not None else f"{country} 未收录（如实显位，不编造）")
    elif concept == "port.calls":
        for p in s.get("ports", []):
            print(f"{p['entity_id']} {p['name_zh']}  max_date={p['max_date']}")
        print("归因口径：" + s.get("attribution_rule", "")[:60] + "…")
    return 0


def cmd_dashboard(pack: Path, out: Path) -> int:
    slices = load_slices(pack)
    policy = slices.get("policy.notice_count", {})
    ports = slices.get("port.calls", {})
    rows_p = "".join(
        f"<tr><td>{c}</td><td>{v}</td></tr>"
        for c, v in (policy.get("latest_month", {}).get("by_country") or {}).items()
    )
    rows_port = "".join(
        f"<tr><td>{p['entity_id']}</td><td>{html.escape(p['name_zh'])}</td><td>{p['max_date']}</td></tr>"
        for p in ports.get("ports", [])
    )
    page = f"""<!doctype html><html lang=zh><meta charset=utf-8>
<title>跨境电商行业线 · 离线看板</title>
<style>body{{font-family:PingFang SC,sans-serif;margin:2rem;background:#fafafa}}
h1{{font-size:1.4rem}} .card{{background:#fff;border:1px solid #e5e5e5;border-radius:8px;padding:1rem 1.5rem;margin:1rem 0}}
table{{border-collapse:collapse}} td,th{{border-bottom:1px solid #eee;padding:.35rem 1.2rem;text-align:left}}
.badge{{background:#eef;border-radius:4px;padding:.1rem .5rem;font-size:.85rem}}</style>
<h1>跨境电商行业线 · 离线看板</h1>
<div class=card><span class=badge>随包基线 as_of {html.escape(as_of(slices))}</span>
<h2>政策通报数（concept 2401，月频）</h2>
<table><tr><th>国家</th><th>通报数/月</th></tr>{rows_p}</table></div>
<div class=card><h2>港口船舶挂靠（concept 2402，周频）</h2>
<table><tr><th>entity_id</th><th>港口</th><th>数据截至</th></tr>{rows_port}</table>
<p style="color:#888">{html.escape(ports.get('attribution_rule', ''))}</p></div>
<div class=card style="color:#666"><b>缺出网依赖如实显位</b>：{html.escape(ONLINE_NOTE)}
（un-comtrade / wto-eping / portwatch-imf / ecb-pboc / mofcom / chinawuliu 走增量通道；merchant-internal=装后商家授权自采）</div>
</html>"""
    out.write_text(page, encoding="utf-8")
    print(f"DASHBOARD → {out}（随包基线渲染，零出网）")
    return 0


def cmd_daily_report(pack: Path, out: Path) -> int:
    slices = load_slices(pack)
    lines = ["# 跨境电商舰队日报（断网模式）", ""]
    lines.append(f"> 数据基线 as_of **{as_of(slices)}**；本报告由随包切片生成，未出网。")
    lines.append("")
    for t in load_fleet_templates(pack):
        lines.append(f"## {t.get('title', t['template'])}（cadence `{t.get('cadence', {}).get('cron', '-')}`）")
        sources = []
        for pos in t.get("positions", []):
            sources += pos.get("sources", [])
        for src in sources or ["xb-baseline"]:
            tag = "随包基线" if src == "xb-baseline" else f"在线增量（{src}）"
            lines.append(f"- 源 `{src}`：{tag}")
        lines.append(f"- 断网行为：{t.get('offline_note', '读随包基线出存量报告，如实标注不更新')}")
        lines.append("")
    lines.append("## 合规分流供给口径")
    p = slices.get("policy.notice_count", {})
    lines.append(f"- 供给=concept 2401（fd-info 无 wto-eping 的纠偏口径）；存量通报 as_of {p.get('latest_month', {}).get('month', '?')}")
    lines.append(f"- 缺出网依赖显位：{ONLINE_NOTE}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"DAILY REPORT → {out}（舰队模板+随包切片，零出网）")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="整机包离线栈（查数/看板/舰队日报）")
    p.add_argument("pack_dir", type=Path)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify")
    q = sub.add_parser("query"); q.add_argument("concept"); q.add_argument("--country")
    d = sub.add_parser("dashboard"); d.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("daily-report"); r.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    if args.cmd == "verify":
        return cmd_verify(args.pack_dir)
    if args.cmd == "query":
        return cmd_query(args.pack_dir, args.concept, args.country)
    if args.cmd == "dashboard":
        return cmd_dashboard(args.pack_dir, args.out)
    return cmd_daily_report(args.pack_dir, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
