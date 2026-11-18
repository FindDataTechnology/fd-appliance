# CI 用来顶替「交付包里的 paas / 内核源码树」的最小服务。
#
# 说明白它在验什么、不验什么：
#   验 —— compose 的分阶段编排（PG 就绪 → migrate → 种子 → paas）、健康门、
#         断网条件下整栈能起来，以及装机编排在真实 docker 上的行为。
#   不验 —— paas 与 fd-erp-ledger-mcp 的业务代码。它们各有自己的仓与流水线；
#         本仓的 compose 只是引用它们（KERNEL_SRC / PAAS_SRC）。
#
# 所以要一个真监听端口的进程，而不是 `sleep infinity`：健康门只有在
# 「进程真的在服务」时才有意义，否则这一步永远是绿的。
FROM python:3.12-slim

# 同时提供 /health（内核那侧的健康门）与 /api/config（paas 那侧的健康门）。
# 两个端口用一个进程起两个 listener，避免为了一个 stub 引 compose。
COPY stub.py /stub.py

EXPOSE 8000 3000
CMD ["python", "/stub.py"]
