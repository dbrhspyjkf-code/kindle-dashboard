#!/bin/sh
# Kindle Dashboard 推送 agent —— 一键安装(在【被监控机】上运行,Linux/macOS)。
# 由看板服务在 /agent/install.sh 提供;在设置页复制带地址的整行命令到目标机运行即可。
#
# 用法:
#   curl -fsSL http://<看板IP>:<端口>/agent/install.sh | sh -s -- http://<看板IP>:<端口> [间隔秒] [标识]
#   卸载:curl -fsSL http://<看板IP>:<端口>/agent/install.sh | sh -s -- uninstall
#
# 装好后:agent 每隔「间隔」秒采集本机指标推给看板;Linux 设 @reboot 自启,macOS 设 launchd 自启。
# 目标机在看板设置页「设备监控」会自动出现(以 hostname 为标识),可在那里改名、选指标。
set -e

# agent 安装目录:优先 KDASH_AGENT_DIR 显式指定;否则挑第一个可写的持久目录。
# 起因:飞牛/群晖/威联通等 NAS 的 SSH 账号家目录常不在 /home(甚至根本没建),
# 直接用 $HOME/.kindle-dash-agent 会因 /home 归 root 不可写而 mkdir 失败(Permission denied)。
_try_dir() {   # $1=base;base 须已存在(不替用户创建家目录/卷根),其下能放 agent 则打印安装目录、返回 0
  [ -n "$1" ] && [ -d "$1" ] || return 1
  _d="$1/.kindle-dash-agent"
  if [ -d "$_d" ] && [ -w "$_d" ]; then printf '%s' "$_d"; return 0; fi
  mkdir -p "$_d" 2>/dev/null || return 1
  [ -w "$_d" ] || return 1
  printf '%s' "$_d"
}
resolve_agent_dir() {
  [ -n "$KDASH_AGENT_DIR" ] && { printf '%s' "$KDASH_AGENT_DIR"; return 0; }
  _uid=$(id -u 2>/dev/null) || _uid=
  _usr=$(id -un 2>/dev/null) || _usr=
  if _try_dir "$HOME"; then return 0; fi
  if _try_dir "$XDG_DATA_HOME"; then return 0; fi
  if [ -n "$_uid" ] && _try_dir "/vol1/$_uid"; then return 0; fi           # 飞牛 fnOS:用户空间在 /vol1/<uid>
  if [ -n "$_usr" ] && _try_dir "/volume1/homes/$_usr"; then return 0; fi  # 群晖 DSM
  if [ -n "$_usr" ] && _try_dir "/share/homes/$_usr"; then return 0; fi    # 威联通 QTS
  if [ -n "$_usr" ] && _try_dir "/vol1/homes/$_usr"; then return 0; fi
  return 1
}
AGENT_DIR="$(resolve_agent_dir || true)"
LABEL="com.kindle-dashboard.agent"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
CRON_TAG="# kindle-dash-agent"

stop_running() {
  # 停掉正在跑的 loop(不依赖 pkill 是否存在)
  if command -v pkill >/dev/null 2>&1; then
    pkill -f "$AGENT_DIR/push_agent.sh" 2>/dev/null || true
  else
    for p in $(ps ax 2>/dev/null | grep "$AGENT_DIR/push_agent.sh" | grep -v grep | awk '{print $1}'); do
      kill "$p" 2>/dev/null || true
    done
  fi
}

uninstall() {
  echo "==> 卸载推送 agent..."
  stop_running
  if [ "$(uname -s)" = "Darwin" ] && command -v launchctl >/dev/null 2>&1; then
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
  fi
  if command -v crontab >/dev/null 2>&1; then
    crontab -l 2>/dev/null | grep -v "$CRON_TAG" | crontab - 2>/dev/null || true
  fi
  [ -n "$AGENT_DIR" ] && rm -rf "$AGENT_DIR"
  echo "✓ 已卸载:停止上报、清开机自启、删除 ${AGENT_DIR:-(无)}。看板设置页那台设备会随之不再更新。"
}

# 内部:打印解析出的安装目录(供安装器自测用,非公开用法)
[ "$1" = "resolve-dir" ] && { printf '%s' "$AGENT_DIR"; exit 0; }
[ "$1" = "uninstall" ] && { uninstall; exit 0; }

URL="$1"
INTERVAL="${2:-30}"
ID="${3:-$(hostname 2>/dev/null || echo unknown)}"
case "$URL" in
  http://*|https://*) : ;;
  *) echo "✗ 用法:curl -fsSL <看板地址>/agent/install.sh | sh -s -- <看板地址> [间隔秒] [标识]"; exit 1 ;;
esac
case "$INTERVAL" in ''|*[!0-9]*) INTERVAL=30 ;; esac
[ "$INTERVAL" -lt 5 ] 2>/dev/null && INTERVAL=30
URL="$(printf '%s' "$URL" | sed 's#/*$##')"   # 去掉末尾斜杠

case "$(uname -s)" in
  Linux)  PLATFORM=linux ;;
  Darwin) PLATFORM=macos ;;
  *) echo "✗ 不支持的系统:$(uname -s)。Windows 请用设置页提供的 PowerShell 命令。"; exit 1 ;;
esac

command -v curl >/dev/null 2>&1 || { echo "✗ 需要 curl,请先安装(NAS 一般自带;或用 wget 改装)"; exit 1; }

if [ -z "$AGENT_DIR" ]; then
  echo "✗ 找不到可写的安装目录:家目录 \$HOME=${HOME:-(空)} 不可写。"
  echo "  常见于飞牛/群晖/威联通等 NAS 的 SSH 账号——家目录不在 /home 或根本没建。"
  echo "  解决:指定一个你有写权限的持久目录后重装(把路径换成你 NAS 上的用户空间),例如:"
  echo "    curl -fsSL $URL/agent/install.sh | KDASH_AGENT_DIR=/vol1/$(id -u 2>/dev/null)/.kindle-dash-agent sh -s -- $URL ${INTERVAL}"
  exit 1
fi

echo "==> 安装到 $AGENT_DIR(系统 =$PLATFORM,间隔 =${INTERVAL}s,标识 =$ID)..."
stop_running
mkdir -p "$AGENT_DIR"
curl -fsSL "$URL/agent/push_agent.sh"          -o "$AGENT_DIR/push_agent.sh"
curl -fsSL "$URL/agent/collect_${PLATFORM}.sh" -o "$AGENT_DIR/collect_${PLATFORM}.sh"
chmod +x "$AGENT_DIR/push_agent.sh" "$AGENT_DIR/collect_${PLATFORM}.sh"
cat > "$AGENT_DIR/agent.env" <<EOF
URL=$URL
ID=$ID
INTERVAL=$INTERVAL
PLATFORM=$PLATFORM
EOF

if [ "$PLATFORM" = "macos" ]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/sh</string><string>$AGENT_DIR/push_agent.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$AGENT_DIR/agent.log</string>
  <key>StandardErrorPath</key><string>$AGENT_DIR/agent.log</string>
</dict>
</plist>
EOF
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load -w "$PLIST" 2>/dev/null && echo "✓ 已设 launchd 自启(登录即跑、退出自动重启)。" \
    || echo "⚠ launchd 加载失败,agent 仍会被下面手动启动,但开机自启没设上。"
else
  # Linux:后台起 + @reboot 自启(cron 最通用;NAS 一般都有)
  ( setsid sh "$AGENT_DIR/push_agent.sh" >"$AGENT_DIR/agent.log" 2>&1 & ) 2>/dev/null \
    || ( nohup sh "$AGENT_DIR/push_agent.sh" >"$AGENT_DIR/agent.log" 2>&1 & )
  if command -v crontab >/dev/null 2>&1; then
    ( crontab -l 2>/dev/null | grep -v "$CRON_TAG"; \
      echo "@reboot sh $AGENT_DIR/push_agent.sh >$AGENT_DIR/agent.log 2>&1 $CRON_TAG" ) | crontab - 2>/dev/null \
      && echo "✓ 已设 @reboot 开机自启。" \
      || echo "⚠ 写 crontab 失败,开机自启没设上(agent 已在跑;重启后重跑本命令即可)。"
  else
    echo "⚠ 没有 crontab,开机自启没设上(agent 已在跑;重启后重跑本命令即可)。"
  fi
fi

echo "✓ 推送 agent 已启动,每 ${INTERVAL} 秒上报一次。"
echo "  回看板设置页「设备监控」→ 这台机器(标识 $ID)会自动出现,可改名、选要显示的指标。"
echo "  卸载:curl -fsSL $URL/agent/install.sh | sh -s -- uninstall"
