"""装机编排：PG 就绪 → 内核 migrate → 种子载入 → paas 启动 → 健康检查。

每一步失败 MUST 在输出里**点名该步**并中止，不进入下一步（design D4）。
姿态同 ``assert_schema_version``：fail-fast 且把能拿到的原因直接打出来，
不让人在「启动了一半」的状态里自己排。

## 为什么「PG 就绪」是单独一步而且必须等

``docker compose up -d postgres`` 在容器进程起来时就返回，而 PG 还在做 initdb。
紧接着跑 migrate 会得到一个「连上了但库不存在/还在恢复」的错误——那与「配置
写错了」长得一模一样，是最容易让人排错排到天亮的一种。compose 里的
``healthcheck`` 给了 ``pg_isready`` 判据，这一步就是等它。

## 为什么 migrate 与 serve 是两个容器

内核运行时绝不发 DDL（``db.py`` 的 ``migrate`` 注释：一次性、可重放、幂等）。
把 migrate 塞进 serve 的启动路径，每次重启都要先抢一把 DDL 锁；而 compose 的
``restart: unless-stopped`` 会让这件事周期性发生。

## 步骤命令可用环境变量覆盖

``APPLIANCE_STEP_<NAME>``（名字里的 ``-`` 换成 ``_`` 并大写）。客户机房的进程
管理未必是 docker compose，但**步名不能改**——报错时点名的就是它。
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, Sequence

#: 默认步骤。种子分两条：科目（seed-accounts，读迁移里的 SQL 函数）与汇率
#: （seed-fx，读随包基线文件）。它们是两件不同的事，合成一步会让「缺了哪一个」
#: 在失败时说不清。
DEFAULT_STEPS: tuple[tuple[str, str], ...] = (
    ("postgres", "docker compose up -d --wait postgres"),
    ("kernel-migrate", "docker compose run --rm kernel fd-erp-ledger-mcp migrate"),
    ("seed-accounts", "docker compose run --rm kernel fd-erp-ledger-mcp seed-accounts"),
    ("seed-fx", "docker compose run --rm kernel fd-erp-ledger-mcp seed-fx /seed/fx-baseline.seed.json"),
    ("paas-start", "docker compose up -d --wait paas"),
    ("health-check", "docker compose exec -T kernel-serve python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3).status==200 else 1)\""),
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
