#!/bin/sh
# ERP 账本恢复（随包件）。**恢复不是「pg_restore 成功」就算完**——那只能证明
# 文件格式对，证明不了数据是同一份。所以这个脚本自己带判据：
#   恢复后重算同一组基线，与备份时的 .baseline **逐项比对**，不一致即失败。
#
# 集群里那次教训：只验 pg_restore 返回码，等于验了「命令没崩」。
#
# 用法：
#   ERP_LEDGER_DATABASE_URL=postgresql://... ./restore.sh <dump 文件>
set -eu

DUMP="${1:?用法: restore.sh <dump 文件>}"
: "${ERP_LEDGER_DATABASE_URL:?缺少 ERP_LEDGER_DATABASE_URL}"
# 同 backup.sh：表在租户 schema 里，不设 search_path 会「恢复成功但一条数据都没有」。
: "${ERP_TENANT_ID:?缺少 ERP_TENANT_ID}"
if [ "$ERP_TENANT_ID" = "default" ]; then TENANT_SCHEMA=public; else TENANT_SCHEMA="tenant_$ERP_TENANT_ID"; fi
export PGOPTIONS="-c search_path=$TENANT_SCHEMA"
[ -s "$DUMP" ] || { echo "FATAL: dump 不存在或为空：$DUMP"; exit 1; }

echo "[1/3] pg_restore（--clean 先清后装：恢复到同一个库时不会与旧表冲突）"
pg_restore --clean --if-exists --no-owner -d "$ERP_LEDGER_DATABASE_URL" "$DUMP"

echo "[2/3] 重算基线"
BASE="$DUMP.baseline"
[ -s "$BASE" ] || { echo "WARN: 没有 $BASE，无法逐项比对（备份时基线查询失败过）"; exit 0; }

ACTUAL=$(psql -At -F'=' -d "$ERP_LEDGER_DATABASE_URL" -c "
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
")

echo "[3/3] 逐项比对"
# 逐行比而不是整块 diff：差在哪一项要说得出名字，否则「不一致」等于没说。
FAIL=0
while IFS= read -r line; do
  [ -n "$line" ] || continue
  key=${line%%=*}
  if printf '%s\n' "$ACTUAL" | grep -qxF "$line"; then
    echo "  ok   $key"
  else
    echo "  DIFF $key：备份时 $(printf '%s\n' "$line" | cut -d= -f2-) / 恢复后 $(printf '%s\n' "$ACTUAL" | grep "^$key=" | cut -d= -f2-)"
    FAIL=1
  fi
done < "$BASE"

[ "$FAIL" -eq 0 ] || { echo "FATAL: 恢复后数据与备份时点不一致"; exit 1; }
echo "restore ok：基线逐项一致"
