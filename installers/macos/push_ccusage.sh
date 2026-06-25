#!/bin/bash
# Kindle Dashboard —— ccusage 采集 + 推送到看板服务
# 在跑 Claude/Codex 的 Mac 上定时执行,把本机 AI 用量推给看板(可以是 NAS 上的服务)。
#
# 推送地址从环境变量 KINDLE_DASH_URL 读(由 launchd 注入);未设置时默认本机 8585。
# 时区从 KINDLE_TZ 读,默认 Asia/Shanghai(ccusage 必带 --timezone,否则按本机时区切天)。
#
# 手动测试:
#   KINDLE_DASH_URL=http://192.168.1.100:8585 bash installers/macos/push_ccusage.sh

URL="${KINDLE_DASH_URL:-http://127.0.0.1:8585}"
TZ_NAME="${KINDLE_TZ:-Asia/Shanghai}"
DEVICE_ID="${KINDLE_DEVICE_ID:-$(hostname -s)}"

export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"

CCUSAGE=""
for c in "$HOME/.npm-global/bin/ccusage" /usr/local/bin/ccusage /opt/homebrew/bin/ccusage; do
    [ -x "$c" ] && CCUSAGE="$c" && break
done
[ -z "$CCUSAGE" ] && CCUSAGE="$(command -v ccusage 2>/dev/null)"
if [ -z "$CCUSAGE" ] || [ ! -x "$CCUSAGE" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') ccusage 未找到,跳过"
    exit 0
fi

CC_JSON=$("$CCUSAGE" claude daily --json --timezone "$TZ_NAME" 2>/dev/null)
CX_JSON=$("$CCUSAGE" codex daily --json --timezone "$TZ_NAME" 2>/dev/null)

[ -z "$CC_JSON" ] && CC_JSON='{"daily":[]}'
[ -z "$CX_JSON" ] && CX_JSON='{"daily":[]}'

BODY=$(cat <<EOF
{"id":"$DEVICE_ID","cc":$CC_JSON,"codex":$CX_JSON}
EOF
)

RESP=$(curl -s -m 30 -X POST "$URL/api/ccusage" \
    -H "Content-Type: application/json" \
    -d "$BODY" 2>&1)

if echo "$RESP" | grep -q '"status"'; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') 推送成功 ($DEVICE_ID) -> $URL/api/ccusage"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') 推送失败: $RESP"
fi
