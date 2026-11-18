"""装机编排：任一步失败必须点名该步并中止，不进入下一步。"""

from __future__ import annotations

import io

from appliance_packer.install import DEFAULT_STEPS, Step, plan, run_install


def test_fail_naming_and_abort():
    """PG 未起 → 输出点名 postgres，后续步骤一次都不执行。"""
    executed: list[str] = []

    def ok(name):
        def run():
            executed.append(name)
            return True, ""
        return run

    def bad(name):
        def run():
            executed.append(name)
            return False, "退出码 1：connection refused"
        return run

    steps = [
        Step("postgres", "", run=bad("postgres")),
        Step("kernel-migrate", "", run=ok("kernel-migrate")),
        Step("seed-load", "", run=ok("seed-load")),
        Step("paas-start", "", run=ok("paas-start")),
        Step("health-check", "", run=ok("health-check")),
    ]
    buf = io.StringIO()
    rc = run_install(steps, out=buf)
    out = buf.getvalue()

    assert rc == 1
    assert "FAILED postgres" in out
    assert "connection refused" in out
    assert "后续步骤未执行" in out
    assert executed == ["postgres"]          # 中止后一步都没跑
    assert "kernel-migrate" not in out.split("FAILED")[1]


def test_all_green_touches_every_step():
    names = [n for n, _ in DEFAULT_STEPS]
    ran: list[str] = []
    steps = [Step(n, "", run=(lambda n=n: (ran.append(n), (True, ""))[1])) for n in names]
    buf = io.StringIO()
    assert run_install(steps, out=buf) == 0
    assert ran == names
    assert f"装机完成：{len(names)}/{len(names)} 步通过" in buf.getvalue()


def test_order_is_pg_first_and_health_last():
    names = [n for n, _ in DEFAULT_STEPS]
    assert names[0] == "postgres"
    assert names[-1] == "health-check"
    assert names.index("postgres") < names.index("kernel-migrate") < names.index("paas-start")
    # 种子必须在 migrate 之后（DDL 先于数据），paas 必须在 kernel-serve 健康之后
    assert names.index("kernel-migrate") < names.index("seed-accounts") < names.index("paas-start")
    assert names.index("kernel-migrate") < names.index("seed-fx") < names.index("paas-start")


def test_step_commands_overridable():
    """客户机房不一定是 compose；单步命令可覆盖但步名不改（点名靠它）。"""
    steps = plan({"APPLIANCE_STEP_HEALTH_CHECK": "curl -fsS http://127.0.0.1:8000/health"})
    health = next(s for s in steps if s.name == "health-check")
    assert health.command == "curl -fsS http://127.0.0.1:8000/health"
    assert [s.name for s in steps] == [n for n, _ in DEFAULT_STEPS]


def test_seed_steps_use_real_kernel_commands():
    """步骤命令必须是内核真实存在的子命令（写错名字 = 装机到这一步才炸）。"""
    from appliance_packer.install import DEFAULT_STEPS
    cmds = {n: c for n, c in DEFAULT_STEPS}
    assert " fd-erp-ledger-mcp migrate" in cmds["kernel-migrate"]
    assert " fd-erp-ledger-mcp seed-accounts" in cmds["seed-accounts"]
    assert " fd-erp-ledger-mcp seed-fx /seed/fx-baseline.seed.json" in cmds["seed-fx"]
    # 上一版写的是不存在的 `seed --file`，这条断言就是为了钉住那次错
    assert " seed --file" not in " ".join(cmds.values())


def test_compose_stack_declares_the_four_required_services():
    """compose 必须提供 minimal_form.required 的那几项（不是占位名）。"""
    from pathlib import Path
    compose = Path(__file__).resolve().parents[1] / "tenants" / "erp" / "compose.yaml"
    text = compose.read_text(encoding="utf-8")
    for service in ("postgres", "paas", "kernel-serve", "kernel"):
        assert f"\n  {service}:" in text, f"compose 缺 service {service}"
    # 机房版形态：不设 AUTH_MODE（默认 none）、不设 CLOUD_MODE。
    # 只看**赋值行**，注释里提到这两个词是说明，不算配置。
    assignments = [
        line.split("#", 1)[0].strip()
        for line in text.splitlines()
        if ":" in line and not line.strip().startswith("#")
    ]
    joined = " ".join(assignments)
    assert "AUTH_MODE:" not in joined, "机房版不应显式设 AUTH_MODE（默认 none 就是它要的）"
    assert "CLOUD_MODE:" not in joined, "CLOUD_MODE 会让身份闸生效，机房版不该开"


def test_missing_binary_is_named_not_crashed():
    ok, reason = Step("postgres", "definitely-not-a-real-binary-xyz").execute()
    assert not ok and "命令不存在" in reason
