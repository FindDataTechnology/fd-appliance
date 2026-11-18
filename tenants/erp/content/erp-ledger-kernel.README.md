# ERP 账本内核（fd-erp-ledger-mcp）— 可打包离线模块

本文件是整机交付包中「ERP 账本内核」组件（class=packable）的随包说明与清单锚点。
服务实体为自包含 MCP 服务 `fd-erp-ledger-mcp`：registry / MCP server 名同名，
import 包 `fd_erp_ledger_mcp`，entry_path `/fd-erp-ledger-mcp`，本位币 CNY，板块标签 ERP（ladder 之外）。

## 为什么可离线、可打进整机包（packable 依据）
- 服务只绑内网 / 回环地址，断公网照常工作：
  - MCP 端点：http://erp-ledger-kernel.internal:8080/mcp
  - 健康检查：http://127.0.0.1:8080/healthz
- 账与库全在客户机房本地：账本库为同机本地 Postgres，回环 127.0.0.1:5432 /
  内网名 erp-ledger-db.svc:5432，库 erp_ledger。余额一律由 journal_entries 重算，
  无直写余额字段；借贷必平由数据库约束触发器强制；已落账分录 append-only（改/删被 DB 拒）。
- 运行期对公网零依赖、零回连：全部 32 个工具面（8 组）在本地库上闭环，不调用任何公网
  SaaS 大模型网关或云厂商专属服务。断公网演示时建账、落账、查询、对账照常工作。

## 工具面（32 个 commercial 工具，8 组；如实口径）
proposal（4）· ledger（2）· recon（2）· billing（9）· credit（4）·
event（4）· object（2）· posting（5）

各组工具名以 `tool-surface.json` 的 `tool_groups` 为准，本节不复述清单——
复述过的那份 8 工具列表已经落后于线上（11-11 上牌事件/对象/过账三组）。
- 两条写入面各自独立：**agent 拟稿**只出 proposal，经 `confirm_proposal`（确认门）才成为事实；**外部系统事实**经 `ingest_event`（导入车道）按来源权威直接成为事实。两者都按人工确认的过账规则（`submit/approve_posting_rule`）派生分录，缺规则即挂待补、不猜科目。
- stable_id 幂等去重（重复提交返回首次结果）；每次响应含 rows_returned 戳；
  长任务立即返回 task_id，状态 排队/进行中/完成/失败，进度不倒退。
- 多币种：原币 + 本位币折算（汇率 + as_of + 出处）；无出处汇率拒绝使用。

## 合规守界（如实，不越界）
- 二清红线：平台只做对账与核对指令层，资金归集 / 代收代付 / 分账走客户自选持牌通道，
  平台不做资金执行。
- 开票 / 税务申报不自研（挂账）：账内可记录发票类事件并参与对账，票据本体由客户
  既有合规渠道处理。
- 对账引擎只读滩头：对外部系统零写入，四类差异（缺失 / 多余 / 金额不符 / 状态不符）
  每条含双侧原始引用，报告落档可查。
- BYOK 凭证经环境变量注入，零落库零日志；租户列隔离 + 跨租户查询闸 + 审计留痕。

## 不宣称（honest caliber）
单体 ERP 应用 / 表单 UI、开票自研、资金执行、网关已上线、谦面市场 live 上架、
registry 快照 live 写入，均不在本包能力内。本包为 publish-ready 交付产物 + 本地校验 /
空跑证据；Live publish / 网关 rollout / registry push / 官网 deploy 属需 live 凭据的
DEPLOY 步骤，本 apply 内挂账、未执行。

## 数据档位
科目表基线、汇率基线随包（ship_with）；汇率日更走在线增量（online_increment）；
客户两源流水与 BYOK 凭证客户自采 / 自持（customer_collects，凭证永不出包）。
逐源档位与离线可得性见同包 sources-tiers 声明与 manifest.data_tiers。
