#!/usr/bin/env bash
# daily_morning.sh — 晨间自动创建今日日报
# 触发时机: 每天 09:00（由 launchd 调用，仅中国工作日）
# 功能:
#   1. 以模板创建 docs/daily/YYYY-MM-DD.md
#   2. 把昨日「明日计划」迁移到今日「今日重点」
#   3. macOS 通知提示

set -euo pipefail

DATA_HUB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_ROOT="$(cd "$DATA_HUB_DIR/.." && pwd)"
REPO_ROOT="$(cd "$TEMPLATE_ROOT/.." && pwd)"
PYTHON="${PYTHON:-$TEMPLATE_ROOT/.venv/bin/python}"

# ── 加载全局配置 ───────────────────────────────────────────
ENV_FILE="$REPO_ROOT/private/agent/.obsidian_daily.env"
if [[ -f "$ENV_FILE" ]]; then
  # 忽略注释和空行，导出环境变量
  export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

# 确保读取到了 OBSIDIAN_VAULT_DIR
VAULT_DIR=$(eval echo "${OBSIDIAN_VAULT_DIR:-$HOME/work/knowledge}")
DAILY_SUBDIR="${OBSIDIAN_DAILY_DIR:-10_Periodic/Daily}"
DAILY_DIR="$VAULT_DIR/$DAILY_SUBDIR"

# ── 日期计算 ──────────────────────────────────────────────
TODAY=$(date +%Y-%m-%d)

# 由 chinese_calendar 覆盖周末、法定节假日和调休工作日。
if ! "$PYTHON" -c "import sys; sys.path.insert(0, '${DATA_HUB_DIR}'); import summary_calendar; raise SystemExit(0 if summary_calendar.should_run_scheduled_event('morning', '${TODAY}') else 1)"; then
  echo "[daily_morning] skip: non-workday $TODAY"
  exit 0
fi

WEEKDAY_NUM=$(date +%u)   # 1=Mon … 7=Sun

WEEKDAY_ZH=("" "星期一" "星期二" "星期三" "星期四" "星期五" "星期六" "星期日")
WEEKDAY="${WEEKDAY_ZH[$WEEKDAY_NUM]}"

YEAR=$(date +%Y)
MONTH=$(date +%m)
MONTH_NUM=$((10#$MONTH))
WEEK=$(date +%V)
QUARTER=$(( (MONTH_NUM - 1) / 3 + 1 ))

OUTFILE="$DAILY_DIR/${TODAY}.md"

# ── 如果今天文件已存在，跳过 ─────────────────────────────
if [[ -f "$OUTFILE" ]]; then
  echo "[daily_morning] $TODAY 日报已存在，跳过创建"
  exit 0
fi

# ── 生成日报文件 ──────────────────────────────────────────
mkdir -p "$DAILY_DIR"

cat > "$OUTFILE" << FRONTMATTER
---
type: journal
status: active
owner: ${USER:-your_name}
date: ${TODAY}
week: ${YEAR}-W$(printf '%02d' "$WEEK")
month: ${YEAR}-$(printf '%02d' "$MONTH_NUM")
quarter: ${YEAR}-Q${QUARTER}
tags: [daily, work-log]
---

# ${YEAR}年$(printf '%02d' "$MONTH_NUM")月$(date +%d)日 ${WEEKDAY}

## 今日重点

PLACEHOLDER_TODO

## 工作记录

<!-- 周报会自动汇总本节列表项 -->

## 临时需求

<!-- 周报会自动汇总本节列表项 -->

## 问题反馈

<!-- 周报会自动汇总本节列表项 -->

## 学习&思考

<!-- 周报会自动汇总本节列表项 -->

## AI 总结

<!-- 由 Summary Engine 写入 70_Summaries/Daily/ -->

## 明日计划

- [ ]

---
关联周报：[[${YEAR}-W$(printf '%02d' "$WEEK")]]
FRONTMATTER

# ── 迁移昨日「明日计划」到今日「今日重点」────────────────
# 找昨天（或最近一个工作日）的日报
YESTERDAY_FILE=""
for i in 1 2 3 4 5; do
  PREV_DATE=$(date -v "-${i}d" +%Y-%m-%d 2>/dev/null || date -d "${i} days ago" +%Y-%m-%d)
  PREV_FILE="$DAILY_DIR/${PREV_DATE}.md"
  if [[ -f "$PREV_FILE" ]]; then
    YESTERDAY_FILE="$PREV_FILE"
    break
  fi
done

if [[ -n "$YESTERDAY_FILE" ]]; then
  # 提取「明日计划」下的 task 行（- [ ] 开头）
  PREV_PLANS=$(awk '/^## 明日计划/{found=1; next} found && /^## /{exit} found && /^- \[/{print}' "$YESTERDAY_FILE")

  if [[ -n "$PREV_PLANS" ]]; then
    # 替换占位符
    ESCAPED_PLANS=$(echo "$PREV_PLANS" | sed 's/\//\\\//g')
    sed -i '' "s/PLACEHOLDER_TODO/${ESCAPED_PLANS}/" "$OUTFILE"
    echo "[daily_morning] 已从 $(basename "$YESTERDAY_FILE") 迁移 $(echo "$PREV_PLANS" | wc -l | tr -d ' ') 条计划"
  else
    sed -i '' "s/PLACEHOLDER_TODO/- [ ] /" "$OUTFILE"
  fi
else
  sed -i '' "s/PLACEHOLDER_TODO/- [ ] /" "$OUTFILE"
fi

echo "[daily_morning] 已创建: $OUTFILE"

# ── macOS 通知 ────────────────────────────────────────────
osascript -e "display notification \"今日日报已创建，开始新的一天 🌅\" with title \"日报助手\" subtitle \"$TODAY $WEEKDAY\"" 2>/dev/null || true
