"""装机编排：PG 就绪 → 内核 migrate → 种子载入 → paas 启动 → 健康检查。

每一步失败 MUST 在输出里**点名该步**并中止，不进入下一步（design D4）。
姿态同 ``assert_schema_version``：fail-fast 且把能拿到的原因直接打出来，
不让人在「启动了一半」的状态里自己排。

步骤命令全部可被环境变量覆盖（``APPLIANCE_STEP_<NAME>``），因为客户机房的
进程管理未必是 docker compose；默认值就是本仓 compose 的形态。
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

#: 默认步骤：名字即报错时点名的那个词，不要改成内部代号。
DEFAULT_STEPS: tuple[tuple[str, str], ...] = (
    ("postgres", "docker compose up -d postgres"),
    ("kernel-migrate", "docker compose run --rm kernel fd-erp-ledger-mcp migrate"),
    ("seed-load", "docker compose run --rm kernel fd-erp-ledger-mcp seed --file /seed/chart-of-accounts.seed.json"),
    ("paas-start", "docker compose up -d paas"),
    ("health-check", "docker compose exec -T paas curl -fsS http://127.0.0.1:3000/api/config"),
)


@dataclass
class Step:
    name: str
    command: str
    timeout_s: float = 300.0
    run: Callable[[], tuple[bool, str]] | None = None  # 测试注入点；None = 跑 command

    def execute(self) -> tuple[bool, str]:
        if self.run is not None:
            return self.run()
        try:
            proc = subprocess.run(
                shlex.split(self.command),
                capture_output=True, text=True, timeout=self.timeout_s,
            )
        except FileNotFoundError as exc:
            return False, f"命令不存在：{exc.filename}"
        except subprocess.TimeoutExpired:
            return False, f"超过 {self.timeout_s:.0f}s 未完成"
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            return False, f"退出码 {proc.returncode}" + (f"：{detail[-1]}" if detail else "")
        return True, ""


def plan(env: dict[str, str] | None = None) -> list[Step]:
    """按默认顺序生成步骤；``APPLIANCE_STEP_<NAME>`` 覆盖单步命令。"""
    env = os.environ if env is None else env
    steps: list[Step] = []
    for name, default in DEFAULT_STEPS:
        key = "APPLIANCE_STEP_" + name.replace("-", "_").upper()
        steps.append(Step(name=name, command=env.get(key) or default))
    return steps


def run_install(steps: Sequence[Step], *, out=sys.stdout) -> int:
    """顺序执行；首个失败即中止并点名。返回 0 或失败步骤的 1-based 序号。"""
    total = len(steps)
    for index, step in enumerate(steps, start=1):
        print(f"[{index}/{total}] {step.name} …", file=out, flush=True)
        started = time.monotonic()
        ok, reason = step.execute()
        elapsed = time.monotonic() - started
        if not ok:
            print(
                f"[{index}/{total}] FAILED {step.name}（{elapsed:.1f}s）：{reason}\n"
                f"装机中止：已停在 {step.name}，后续步骤未执行。修复后从该步重跑。",
                file=out, flush=True,
            )
            return index
        print(f"[{index}/{total}] ok     {step.name}（{elapsed:.1f}s）", file=out, flush=True)
    print(f"装机完成：{total}/{total} 步通过", file=out)
    return 0
