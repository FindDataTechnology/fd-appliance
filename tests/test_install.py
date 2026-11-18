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
    assert "装机完成：5/5 步通过" in buf.getvalue()


def test_order_is_pg_first_and_health_last():
    names = [n for n, _ in DEFAULT_STEPS]
    assert names[0] == "postgres"
    assert names[-1] == "health-check"
    assert names.index("postgres") < names.index("kernel-migrate") < names.index("paas-start")


def test_step_commands_overridable(monkeypatch):
    """客户机房不一定是 compose；单步命令可覆盖但步名不改（点名靠它）。"""
    steps = plan({"APPLIANCE_STEP_HEALTH_CHECK": "curl -fsS http://127.0.0.1:3000/api/config"})
    health = next(s for s in steps if s.name == "health-check")
    assert health.command == "curl -fsS http://127.0.0.1:3000/api/config"
    assert [s.name for s in steps] == [n for n, _ in DEFAULT_STEPS]


def test_missing_binary_is_named_not_crashed():
    ok, reason = Step("postgres", "definitely-not-a-real-binary-xyz").execute()
    assert not ok and "命令不存在" in reason
