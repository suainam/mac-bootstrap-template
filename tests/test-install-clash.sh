#!/usr/bin/env bash
# test-install-clash.sh — Unit tests for install-clash.sh
# Uses simple bash assertions (no external test framework).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$SCRIPT_DIR/scripts/install-clash.sh"

PASS=0
FAIL=0
TESTS=()

# --- Test helpers ---
assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  ✅ $desc"
    PASS=$((PASS + 1))
  else
    echo "  ❌ $desc"
    echo "     expected: $expected"
    echo "     actual:   $actual"
    FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local desc="$1" haystack="$2" needle="$3"
  if echo "$haystack" | grep -q "$needle"; then
    echo "  ✅ $desc"
    PASS=$((PASS + 1))
  else
    echo "  ❌ $desc"
    echo "     expected to contain: $needle"
    echo "     actual: $haystack"
    FAIL=$((FAIL + 1))
  fi
}

assert_exit_code() {
  local desc="$1" expected="$2" actual="$3"
  assert_eq "$desc (exit code)" "$expected" "$actual"
}

run_test() {
  local name="$1"
  echo ""
  echo "--- $name ---"
  TESTS+=("$name")
}

# --- Source functions from script (extract for testing) ---
# We source the script functions by extracting them
extract_function() {
  local func_name="$1"
  # Create a temp file with just the function
  local tmpfile="/tmp/test-func-$func_name.sh"
  awk "/^${func_name}\(\)/,/^}/" "$SCRIPT" > "$tmpfile"
  echo "$tmpfile"
}

# ============================================================
# Test 1: Script exists and is executable
# ============================================================
run_test "Script exists and is executable"
if [ -x "$SCRIPT" ]; then
  echo "  ✅ Script is executable"
  PASS=$((PASS + 1))
else
  echo "  ❌ Script is not executable"
  FAIL=$((FAIL + 1))
fi

# ============================================================
# Test 2: --help flag
# ============================================================
run_test "--help flag"
output=$(bash "$SCRIPT" --help 2>&1 || true)
assert_contains "Shows usage" "$output" "Usage:"
# Use fixed strings (fgrep) to avoid grep interpreting -- as option
if echo "$output" | grep -F -- "--dry-run" > /dev/null 2>&1; then
  echo "  ✅ Mentions --dry-run"
  PASS=$((PASS + 1))
else
  echo "  ❌ Mentions --dry-run"
  FAIL=$((FAIL + 1))
fi
if echo "$output" | grep -F -- "--force" > /dev/null 2>&1; then
  echo "  ✅ Mentions --force"
  PASS=$((PASS + 1))
else
  echo "  ❌ Mentions --force"
  FAIL=$((FAIL + 1))
fi

# ============================================================
# Test 3: Unknown flag
# ============================================================
run_test "Unknown flag"
output=$(bash "$SCRIPT" --unknown-flag 2>&1) && exit_code=0 || exit_code=$?
assert_exit_code "Exits with code 2" "2" "$exit_code"
assert_contains "Shows error" "$output" "Unknown"

# ============================================================
# Test 4: detect_arch function
# ============================================================
run_test "detect_arch function"
# Source the script functions by extracting detect_arch
{
  echo 'set -euo pipefail'
  awk '/^detect_arch\(\)/,/^}/' "$SCRIPT"
  echo 'detect_arch'
} > /tmp/test-detect-arch.sh
arch_output=$(bash /tmp/test-detect-arch.sh 2>&1)
# On this machine, should be aarch64 or x64
if [ "$(uname -m)" = "arm64" ]; then
  assert_eq "arm64 -> aarch64" "aarch64" "$arch_output"
else
  assert_eq "x86_64 -> x64" "x64" "$arch_output"
fi

# ============================================================
# Test 5: build_download_url function
# ============================================================
run_test "build_download_url function"
{
  echo 'set -euo pipefail'
  echo 'REPO="clash-verge-rev/clash-verge-rev"'
  awk '/^build_download_url\(\)/,/^}/' "$SCRIPT"
  echo 'build_download_url "v2.4.7" "aarch64"'
} > /tmp/test-build-url.sh
url_output=$(bash /tmp/test-build-url.sh 2>&1)
assert_eq "Correct URL for aarch64" \
  "https://github.com/clash-verge-rev/clash-verge-rev/releases/download/v2.4.7/Clash.Verge_2.4.7_aarch64.dmg" \
  "$url_output"

{
  echo 'set -euo pipefail'
  echo 'REPO="clash-verge-rev/clash-verge-rev"'
  awk '/^build_download_url\(\)/,/^}/' "$SCRIPT"
  echo 'build_download_url "v2.4.7" "x64"'
} > /tmp/test-build-url-x64.sh
url_output_x64=$(bash /tmp/test-build-url-x64.sh 2>&1)
assert_eq "Correct URL for x64" \
  "https://github.com/clash-verge-rev/clash-verge-rev/releases/download/v2.4.7/Clash.Verge_2.4.7_x64.dmg" \
  "$url_output_x64"

# ============================================================
# Test 6: --dry-run does not execute downloads
# ============================================================
run_test "--dry-run does not execute"
output=$(bash "$SCRIPT" --dry-run --force 2>&1) && exit_code=0 || exit_code=$?
# Should show DRY-RUN for curl commands but not actually download
assert_contains "Shows DRY-RUN" "$output" "DRY-RUN"
assert_contains "Shows architecture" "$output" "Architecture:"
assert_contains "Shows version" "$output" "Latest version:"
# Should not create any files in /tmp
if [ -d "/tmp/clash-verge-install" ]; then
  echo "  ❌ Created download dir in dry-run mode"
  FAIL=$((FAIL + 1))
else
  echo "  ✅ No download dir created in dry-run"
  PASS=$((PASS + 1))
fi

# ============================================================
# Test 7: Mirror list is not empty
# ============================================================
run_test "Mirror list configuration"
{
  echo 'set -euo pipefail'
  awk '/^MIRRORS=\(/,/\)/' "$SCRIPT" | head -20
  echo 'echo "${#MIRRORS[@]}"'
} > /tmp/test-mirrors.sh
mirror_count=$(bash /tmp/test-mirrors.sh 2>&1)
assert_eq "At least 3 mirrors configured" "4" "$mirror_count"

# ============================================================
# Test 8: Already installed (without --force)
# ============================================================
run_test "Already installed check"
# Create a fake app path
FAKE_APP="/tmp/test-clash-verge-install-test/Clash Verge.app"
mkdir -p "$FAKE_APP"
# Temporarily override APP_PATH in script
output=$(APP_PATH="$FAKE_APP" bash "$SCRIPT" 2>&1) && exit_code=0 || exit_code=$?
assert_contains "Detects existing install" "$output" "already installed"
rm -rf "/tmp/test-clash-verge-install-test"

# ============================================================
# Test 9: SHA256 verification function exists
# ============================================================
run_test "verify_checksum function exists"
if grep -q "^verify_checksum()" "$SCRIPT"; then
  echo "  ✅ verify_checksum function defined"
  PASS=$((PASS + 1))
else
  echo "  ❌ verify_checksum function not found"
  FAIL=$((FAIL + 1))
fi

# ============================================================
# Test 10: Script has proper shebang and set -euo pipefail
# ============================================================
run_test "Script safety"
first_line=$(head -1 "$SCRIPT")
assert_eq "Has bash shebang" "#!/usr/bin/env bash" "$first_line"
if grep -q "set -euo pipefail" "$SCRIPT"; then
  echo "  ✅ Has set -euo pipefail"
  PASS=$((PASS + 1))
else
  echo "  ❌ Missing set -euo pipefail"
  FAIL=$((FAIL + 1))
fi

# ============================================================
# Summary
# ============================================================
echo ""
echo "=========================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "=========================================="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
