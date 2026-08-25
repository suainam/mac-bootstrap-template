#!/usr/bin/env bash
# qa-watch.sh: Test failure watcher with loop protection (Luvus).
# Runs the test suite periodically; on failure, alerts 'agent' pane via luvus agent send.
#
# Env knobs:
#   QA_TEST_CMD   - command to run (default: "npm run test:dev-topology")
#   QA_COOLDOWN   - seconds between runs (default: 15)
#   QA_MAX_ALERTS - max consecutive alerts before pausing (default: 3)

set -uo pipefail

TARGET_PANE="${QA_TARGET_PANE:-agent}"
TEST_CMD="${QA_TEST_CMD:-npm run test:dev-topology}"
COOLDOWN_SEC="${QA_COOLDOWN:-15}"
MAX_CONSECUTIVE_ALERTS="${QA_MAX_ALERTS:-3}"

FAIL_COUNT=0
LAST_FAIL_HASH=""

calc_md5() {
  if command -v md5 >/dev/null 2>&1; then md5 -q; else md5sum | awk '{print $1}'; fi
}

echo "🛡️  [qa-watch] watching '$TEST_CMD' → alerts → pane:$TARGET_PANE (luvus)"

while true; do
  OUTPUT=$(eval "$TEST_CMD" 2>&1)

  if echo "$OUTPUT" | grep -qE "fail [1-9]|ERR_|Error:|AssertionError"; then
    CURRENT_HASH=$(echo "$OUTPUT" | calc_md5)
    if [ "$CURRENT_HASH" != "$LAST_FAIL_HASH" ]; then
      FAIL_COUNT=$((FAIL_COUNT + 1))
      LAST_FAIL_HASH="$CURRENT_HASH"
      if [ $FAIL_COUNT -le $MAX_CONSECUTIVE_ALERTS ]; then
        LOG_SAMPLE=$(echo "$OUTPUT" | tail -n 25)
        echo "⚠️  [qa-watch #$FAIL_COUNT] failure detected → alerting agent"
        luvus agent send "$TARGET_PANE" "【QA 自动报警 #$FAIL_COUNT】测试失败，请修复：
\`\`\`
$LOG_SAMPLE
\`\`\`" 2>/dev/null || true
      else
        echo "⏸️  [qa-watch] max consecutive alerts reached ($MAX_CONSECUTIVE_ALERTS); paused"
      fi
    fi
  else
    [ $FAIL_COUNT -gt 0 ] && echo "✅ [qa-watch] recovered"
    FAIL_COUNT=0
    LAST_FAIL_HASH=""
  fi

  sleep "$COOLDOWN_SEC"
done
