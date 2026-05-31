#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)"
SHELL_ENV="$DIR/shell/shell_env"

HTTP_PROXY_VAL=$(grep '^export http_proxy=' "$SHELL_ENV" | sed 's/.*=//' | tr -d '"')
HTTPS_PROXY_VAL=$(grep '^export https_proxy=' "$SHELL_ENV" | sed 's/.*=//' | tr -d '"')

echo "=== npm proxy ==="
npm config set proxy "$HTTP_PROXY_VAL"
npm config set https-proxy "$HTTPS_PROXY_VAL"
echo "  npm proxy 已配置"

echo ""
echo "代理源：shell/shell_env  |  Docker/Colima 自动读取环境变量"
