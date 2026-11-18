#!/bin/sh
# ERP 账本备份（随包件，机房版用）。
#
# 从集群里的 erp-ledger-backup CronJob 提炼：**判据照搬，集群特有的部分去掉**。
# 去掉的是「异地 rsync 到备份机」——那是我们的基础设施，客户机房没有；客户要异地
# 就自己把这个脚本挂到 cron + rsync 上去。
#
# 用法：
#   ERP_LEDGER_DATABASE_URL=postgresql://... ./backup.sh [输出目录]
#
# 为什么不是「pg_dump 一下就行」——这三条都是集群里踩出来的：
#   1. `.part` 中间态：任何失败路径都不能留下半成品，否则巡检/恢复会拿它当可用备份。
#   2. **整包通读**验完整性：`pg_restore -l` 只读文件头的 TOC，截断包照样能列目录
#      （假绿）。必须 `pg_restore --file=/dev/null` 把数据块全读一遍。
#   3. **时点基线**：光有 dump，恢复后无法证明「数据一致」。基线记下分录条数、
#      借贷合计、余额指纹，恢复后重算比对——这才是 4.4 的判据。
set -eu

: "${ERP_LEDGER_DATABASE_URL:?缺少 ERP_LEDGER_DATABASE_URL（记账本是哪张库）}"
# 表在租户 schema 里，不在 public。pg_dump/psql 默认连 public，不指定就**一条也看不到**——
# 表现为「备份成功但只有 100K」「基线查询失败」，而这两个都不像错。
# ERP_TENANT_ID=default 时 schema 是 public（内核的 schema_for 就是这么映射的）。
: "${ERP_TENANT_ID:?缺少 ERP_TENANT_ID（表在哪个租户 schema）}"
if [ "$ERP_TENANT_ID" = "default" ]; then
  TENANT_SCHEMA=public
else
  TENANT_SCHEMA="tenant_$ERP_TENANT_ID"
fi
export PGOPTIONS="-c search_path=$TENANT_SCHEMA"
BACKUP_DIR="${1:-${BACKUP_DIR:-./backups}}"
mkdir -p "$BACKUP_DIR"

STAMP=$(date -u +%Y%m%d-%H%M%S)
OUT="$BACKUP_DIR/erp-ledger-$STAMP.dump"
PART="$OUT.part"
trap 'rm -f "$PART"' EXIT

echo "[1/4] dump（-Fc：压缩 + 可整包校验 + 可选择性恢复；只打本租户 schema）"
# --schema 只打本租户：多租户共用一库时，不加它会把**别人的**数据一起备份出来
# （既是爆炸半径问题，也是合规问题）。
pg_dump -Fc --no-owner --schema="$TENANT_SCHEMA" -d "$ERP_LEDGER_DATABASE_URL" -f "$PART"
[ -s "$PART" ] || { echo "FATAL: dump 为空（0 字节）"; exit 1; }

echo "[2/4] 整包通读（截断/损坏在这里报错）"
if ! pg_restore --file=/dev/null --no-owner "$PART"; then
  echo "FATAL: 整包通读失败（备份损坏或截断，不标记为可用）"
  exit 1
fi
mv "$PART" "$OUT"

echo "[3/4] 时点基线（恢复后拿它比对）"
# 基线查询失败只 WARN：备份本身已通过整包校验，不因基线把好备份判废。
psql -At -F'=' -d "$ERP_LEDGER_DATABASE_URL" -c "
  select 'entries', count(*)::text from journal_entries
  union all select 'debit_total_base',
    coalesce(sum(amount_base) filter (where direction='debit'), 0)::text from journal_entries
  union all select 'credit_total_base',
    coalesce(sum(amount_base) filter (where direction='credit'), 0)::text from journal_entries
  union all select 'accounts', count(*)::text from accounts
  union all select 'proposals_confirmed',
    count(*)::text from proposals where status='confirmed'
  union all select 'balance_fingerprint', coalesce(md5(string_agg(t, '|' order by t)), 'empty')
    from (select account_code||':'||direction||':'||sum(amount_base) t
          from journal_entries group by account_code, direction) s
" > "$OUT.baseline" 2>/dev/null || {
    echo "WARN: 基线查询失败（备份本身已通过整包通读，仍可用）"
    rm -f "$OUT.baseline"
  }

echo "[4/4] 保留最近 30 份"
ls -1t "$BACKUP_DIR"/erp-ledger-*.dump 2>/dev/null | tail -n +31 | xargs -r rm -f
for f in "$BACKUP_DIR"/erp-ledger-*.dump.baseline; do
  [ -e "$f" ] || continue
  [ -e "${f%.baseline}" ] || rm -f "$f"
done

echo "backup ok: $OUT（$(du -h "$OUT" | cut -f1)）"
[ -f "$OUT.baseline" ] && echo "baseline: $(tr '\n' ' ' < "$OUT.baseline")"
echo "校验方式：./restore.sh $OUT <目标 DSN>，它会重算基线并与 .baseline 逐项比对"
