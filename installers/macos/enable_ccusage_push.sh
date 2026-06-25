#!/bin/bash
# Kindle Dashboard —— 一键启用「AI 用量(ccusage)推送」(仅 macOS)
#
# 谁会调它:
#   1) install.sh 选「是」时;
#   2) 用户后来自己在终端跑(或设置页复制命令)。
#
# 做两件事:
#   1) 装 launchd 定时器,每隔 ai_usage.interval 秒跑 push_ccusage.sh 采集本机 Claude/Codex 用量推给看板。
#   2) 前台跑一次,确认连通。
#
# 参数:
#   --url <看板地址>  指定推送目标(NAS 部署时用),如 --url http://192.168.1.100:8585
#                    不传则默认 http://127.0.0.1:<config里的port>(单机模式)
#
# 幂等,可重复运行。
# 测试用:KINDLE_SKIP_AGENT=1 跳过 launchd(供 CI/非 Mac 验证)。

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
CONFIG="${KINDLE_CONFIG:-$HOME/.config/kindle-dashboard/config.yaml}"
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
LABEL="com.kindle-dashboard.ccusage-push"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PUSH_SH="$REPO/installers/macos/push_ccusage.sh"

die(){ echo "✗ $1"; exit 1; }

[ -f "$CONFIG" ] || die "没找到 config.yaml($CONFIG)。请先跑一次 install.sh。"
[ -n "$PY" ]     || die "未找到 python3。"

# 解析 --url 参数
TARGET_URL=""
while [ $# -gt 0 ]; do
    case "$1" in
        --url) TARGET_URL="$2"; shift 2 ;;
        *) shift ;;
    esac
done

PORT=$("$PY" -c "import yaml;print((yaml.safe_load(open('$CONFIG')) or {}).get('server',{}).get('port',8585))" 2>/dev/null || echo 8585)
[ -z "$TARGET_URL" ] && TARGET_URL="http://127.0.0.1:$PORT"
INTERVAL=$("$PY" -c "import yaml;v=(yaml.safe_load(open('$CONFIG')) or {}).get('ai_usage',{}).get('interval',300);print(v if isinstance(v,int) and v>=30 else 300)" 2>/dev/null || echo 300)
TZ_NAME=$("$PY" -c "import yaml;print((yaml.safe_load(open('$CONFIG')) or {}).get('server',{}).get('timezone','Asia/Shanghai'))" 2>/dev/null || echo "Asia/Shanghai")

# 确保配置启用 AI 用量
"$PY" - "$CONFIG" <<'PYEOF'
import sys, yaml
p = sys.argv[1]
with open(p, encoding="utf-8") as f:
    c = yaml.safe_load(f) or {}
c.setdefault("ai_usage", {})["enabled"] = True
with open(p, "w", encoding="utf-8") as f:
    yaml.safe_dump(c, f, allow_unicode=True, sort_keys=False)
PYEOF
[ $? -eq 0 ] || die "写配置失败。"
echo "✓ 已在配置中启用 AI 用量页"

# 测试 / 非 Mac:到此为止
if [ "$KINDLE_SKIP_AGENT" = "1" ]; then
    echo "(KINDLE_SKIP_AGENT=1:跳过 launchd 安装)"; exit 0
fi
if ! command -v launchctl >/dev/null 2>&1; then
    echo "⚠ 当前不是 macOS,跳过 launchd。ccusage 推送只在 Mac 上有效。"; exit 0
fi

[ -f "$PUSH_SH" ] || die "缺少推送脚本:$PUSH_SH"
chmod +x "$PUSH_SH"

# 装 launchd agent
mkdir -p "$HOME/Library/LaunchAgents" "$REPO/data"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$PUSH_SH</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>KINDLE_DASH_URL</key><string>$TARGET_URL</string>
    <key>KINDLE_TZ</key><string>$TZ_NAME</string>
    <key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
  </dict>
  <key>StartInterval</key><integer>$INTERVAL</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$REPO/data/ccusage-push.log</string>
  <key>StandardErrorPath</key><string>$REPO/data/ccusage-push.log</string>
</dict>
</plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
if launchctl load -w "$PLIST" 2>/dev/null; then
    echo "✓ ccusage 推送已安装(每 ${INTERVAL} 秒推送一次 → $TARGET_URL)"
else
    echo "⚠ launchd 加载失败。"; exit 1
fi

# 前台跑一次确认连通
echo "==> 立即推送一次..."
KINDLE_DASH_URL="$TARGET_URL" KINDLE_TZ="$TZ_NAME" /bin/bash "$PUSH_SH"
echo
echo "✓ 完成。停用:bash installers/macos/disable_ccusage_push.sh"
