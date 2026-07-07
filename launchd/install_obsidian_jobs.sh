#!/usr/bin/env bash
# install_obsidian_jobs.sh — 一键安装 macOS launchd 定时任务
#
# 此脚本将配置并启动以下定时任务：
#   09:00  → daily_morning.sh (创建日报 + 迁移昨日计划)
#   17:30  → reminder notification
#   18:00  → run-daily-evening.sh (全链路：ingest → auto_review → materialize → summary)
#   周五/节前 18:00  → weekly_summary.py (生成周报)

set -euo pipefail

MAC_BOOTSTRAP_DIR="$HOME/work/config/mac-bootstrap"
DATA_HUB_DIR="$MAC_BOOTSTRAP_DIR/template/agent/data-hub"
SCRIPTS_DIR="$DATA_HUB_DIR/scripts"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/agent-data-hub"

MORNING_LABEL="com.${USER}.daily-morning"
REMINDER_LABEL="com.${USER}.daily-reminder"
EVENING_LABEL="com.${USER}.daily-evening"
WEEKLY_LABEL="com.${USER}.weekly-summary"

MORNING_PLIST="$LAUNCH_AGENTS_DIR/${MORNING_LABEL}.plist"
REMINDER_PLIST="$LAUNCH_AGENTS_DIR/${REMINDER_LABEL}.plist"
EVENING_PLIST="$LAUNCH_AGENTS_DIR/${EVENING_LABEL}.plist"
WEEKLY_PLIST="$LAUNCH_AGENTS_DIR/${WEEKLY_LABEL}.plist"

PYTHON="$(which python3)"

mkdir -p "$LOG_DIR"

# ── 卸载模式 ─────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
  for label in "$MORNING_LABEL" "$REMINDER_LABEL" "$EVENING_LABEL" "$WEEKLY_LABEL"; do
    launchctl unload "$LAUNCH_AGENTS_DIR/${label}.plist" 2>/dev/null && echo "已卸载 $label" || true
    rm -f "$LAUNCH_AGENTS_DIR/${label}.plist"
  done
  echo "✅ 已卸载所有定时任务"
  exit 0
fi

chmod +x "$DATA_HUB_DIR/daily_morning.sh"
chmod +x "$DATA_HUB_DIR/run-daily-evening.sh"
chmod +x "$SCRIPTS_DIR/weekly_summary.py"

# ── 1. 晨间任务: 09:00 创建日报 ──────────────────────────
cat > "$MORNING_PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${MORNING_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${DATA_HUB_DIR}/daily_morning.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/morning.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/morning.err</string>
    <key>RunAtLoad</key>
    <false/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>${HOME}</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>
EOF

# ── 2. 提醒任务: 17:30 提醒填写工作记录 ──────────────────
cat > "$REMINDER_PLIST" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${REMINDER_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/osascript</string>
        <string>-e</string>
        <string>display notification "记得填写今天的工作记录 📝 AI 总结将在 18:00 生成" with title "日报助手" sound name "Glass"</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>17</integer>
        <key>Minute</key>
        <integer>30</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/reminder.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/reminder.err</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST_EOF

# ── 3. 晚间任务: 18:00 全链路 ────────────────────────────
cat > "$EVENING_PLIST" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${EVENING_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${DATA_HUB_DIR}/run-daily-evening.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>18</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/evening.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/evening.err</string>
    <key>RunAtLoad</key>
    <false/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>${HOME}</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>
PLIST_EOF

# ── 4. 周报任务: 每个工作日 18:00 (脚本内判断是否需要生成) ────
cat > "$WEEKLY_PLIST" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${WEEKLY_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON}</string>
        <string>${SCRIPTS_DIR}/weekly_summary.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <dict>
            <key>Weekday</key>
            <integer>1</integer>
            <key>Hour</key>
            <integer>18</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Weekday</key>
            <integer>2</integer>
            <key>Hour</key>
            <integer>18</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Weekday</key>
            <integer>3</integer>
            <key>Hour</key>
            <integer>18</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Weekday</key>
            <integer>4</integer>
            <key>Hour</key>
            <integer>18</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Weekday</key>
            <integer>5</integer>
            <key>Hour</key>
            <integer>18</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
    </array>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/weekly.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/weekly.err</string>
    <key>RunAtLoad</key>
    <false/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>${HOME}</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>
PLIST_EOF

# ── 加载任务 ─────────────────────────────────────────────
for plist in "$MORNING_PLIST" "$REMINDER_PLIST" "$EVENING_PLIST" "$WEEKLY_PLIST"; do
  launchctl unload "$plist" 2>/dev/null || true
  launchctl load "$plist"
  echo "✅ 已加载: $(basename "$plist")"
done

echo ""
echo "🎉 Agent Data Hub 定时任务安装完成！"
echo "   09:00  创建今日日报 + 迁移昨日计划"
echo "   17:30  提醒填写工作记录"
echo "   18:00  全链路：ingest → auto_review → materialize → summary"
echo "   周五 18:00  生成周报"
echo ""
echo "日志目录: $LOG_DIR"
echo "配置目录: $MAC_BOOTSTRAP_DIR/private/agent/.obsidian_daily.env"
echo "手动测试晚间: bash $DATA_HUB_DIR/run-daily-evening.sh"
echo "手动测试周报: ${PYTHON} $SCRIPTS_DIR/weekly_summary.py"
