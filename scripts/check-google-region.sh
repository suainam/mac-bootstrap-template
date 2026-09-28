#!/usr/bin/env bash
# 检测当前出口 IP 或指定代理是否被 Google “送中”

set -euo pipefail

PROXY="${1:-${all_proxy:-${http_proxy:-}}}"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"

CURL_OPTS=("-s" "-m" "10" "-A" "$UA")
if [ -n "$PROXY" ]; then
    CURL_OPTS+=("-x" "$PROXY")
fi

echo "══════════════════════════════════════════════════"
echo "        Google 送中与 Gemini 可用性快速检测器       "
echo "══════════════════════════════════════════════════"
[ -n "$PROXY" ] && echo "代理端点: $PROXY"

# 1. 检查出口 IP
echo -n "🔍 正在探测出口 IP 基础信息... "
IP_JSON=$(curl "${CURL_OPTS[@]}" https://ipinfo.io/json 2>/dev/null || echo "{}")
IP=$(echo "$IP_JSON" | jq -r '.ip // empty' 2>/dev/null || echo "未知")
CITY=$(echo "$IP_JSON" | jq -r '.city // empty' 2>/dev/null || echo "")
COUNTRY=$(echo "$IP_JSON" | jq -r '.country // empty' 2>/dev/null || echo "")
ORG=$(echo "$IP_JSON" | jq -r '.org // empty' 2>/dev/null || echo "")
echo "完成"
echo "   出口 IP: $IP ($CITY, $COUNTRY, $ORG)"

# 2. 检查 Google Variations Seed (最权威判定指标)
echo -n "🔍 正在向 Google 客户端种子服务器探测归属国... "
SEED_HEADERS=$(curl "${CURL_OPTS[@]}" -I https://clients4.google.com/chrome-variations/seed 2>/dev/null || true)
X_COUNTRY=$(echo "$SEED_HEADERS" | (grep -i "^x-country:" || true) | awk '{print $2}' | tr -d '\r\n' | tr '[:upper:]' '[:lower:]')
X_GEO=$(echo "$SEED_HEADERS" | (grep -i "^x-geo-level-1:" || true) | awk '{print $2}' | tr -d '\r\n')
echo "完成"
echo "   Google 种子识别 (x-country): ${X_COUNTRY:-未知} ${X_GEO:+(地区: $X_GEO)}"

# 3. 检查 Google.com 首页重定向
echo -n "🔍 正在检查 Google 首页访问策略... "
G_HEADERS=$(curl "${CURL_OPTS[@]}" -i https://www.google.com 2>/dev/null || true)
HTTP_CODE=$(echo "$G_HEADERS" | grep -E "^HTTP/" | sed -n '1p' | awk '{print $2}' || true)
LOCATION=$(echo "$G_HEADERS" | grep -i "^location:" | awk '{print $2}' | tr -d '\r\n' || true)
echo "完成"

if [ -n "$LOCATION" ]; then
    echo "   首页跳转: HTTP $HTTP_CODE -> $LOCATION"
else
    echo "   首页直连: HTTP $HTTP_CODE (无地域重定向)"
fi

# 4. 判定结论
echo "──────────────────────────────────────────────────"
if [[ "$X_COUNTRY" == "cn" || "$X_COUNTRY" == "hk" || "$LOCATION" == *"google.com.hk"* ]]; then
    echo "❌ 结论: 该节点已被 Google 【送中】！"
    echo "   - 原因: Google 内部数据库将该出口 IP 判定为 中国大陆 / 香港"
    echo "   - 影响: Chrome Gemini 侧边栏及 gemini.google.com 将被硬阻断（提示不在可用区）"
    echo "   - 建议: 请在代理客户端切换其他未送中的纯净节点"
elif [ -z "$X_COUNTRY" ]; then
    echo "⚠️ 结论: 连接 Google 种子节点超时或受阻，请检查节点代理连通性"
else
    UPPER_C=$(echo "$X_COUNTRY" | tr '[:lower:]' '[:upper:]')
    echo "✅ 结论: 该节点【纯净未送中】！"
    echo "   - 区域: Google 识别为 $UPPER_C (支持 Gemini、Chrome AI 侧边栏全功能)"
fi
echo "══════════════════════════════════════════════════"
