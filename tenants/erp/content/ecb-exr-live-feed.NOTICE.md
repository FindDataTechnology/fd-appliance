# ecb-exr 实时汇率观测流 — 不入包（cloud_locked）

- 组件分类：cloud_locked，实时公网拉取能力严禁随包（vertical-appliance-delivery 可私有化不变量）。
- 原因：实时汇率观测需出网访问公网数据源，客户机房断网环境下不可用；包内不得含任何
  公网硬地址 / 硬编码 IP。
- 替代（substitute）：随包仅「近 12 月汇率基线切片」（见 fx-baseline.seed.json，
  ship_with 档，断网供折算基线）；日更增量走 online_increment 档，由客户侧出网或
  中转拉取后离线导入；无出处汇率一律拒绝使用。
- 守界：本包不内置任何公网数据端点；实时抓取能力归在线增量通道，不在整机包内。
