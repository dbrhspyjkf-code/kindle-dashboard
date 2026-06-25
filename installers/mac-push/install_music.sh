#!/bin/sh
# Kindle Dashboard —— 一键安装「Apple Music 当前播放推送」(macOS,独立,不需要 clone 仓库)。
# 由看板 NAS 服务在 /agent/install_music.sh 下发;设置页给一行命令。
#
# 用法:
#   curl -fsSL http://<NAS>:8585/agent/install_music.sh | sh -s -- http://<NAS>:8585 [间隔秒]
#   卸载: curl -fsSL http://<NAS>:8585/agent/install_music.sh | sh -s -- uninstall
#
# 装好后:每隔「间隔」秒读 Mac 上的 Music.app 当前播放,推给 NAS 看板。
set -e

DIR="$HOME/.kindle-dashboard"
LABEL="com.kindle-dashboard.music"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

uninstall() {
  echo "==> 卸载 Apple Music 推送..."
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  rm -f "$DIR/read_music.js" "$DIR/sync_music.sh" "$DIR/music_artwork.jpg" "$DIR/music_artwork.sha256"
  echo "✓ 已卸载 Apple Music 推送。"
}

[ "$1" = "uninstall" ] && { uninstall; exit 0; }

URL="$1"
INTERVAL="${2:-5}"
case "$URL" in
  http://*|https://*) : ;;
  *) echo "✗ 用法: curl -fsSL <NAS地址>/agent/install_music.sh | sh -s -- <NAS地址> [间隔秒]"; exit 1 ;;
esac
case "$INTERVAL" in ''|*[!0-9]*) INTERVAL=5 ;; esac
[ "$INTERVAL" -lt 2 ] 2>/dev/null && INTERVAL=5
URL="$(printf '%s' "$URL" | sed 's#/*$##')"

[ "$(uname -s)" = "Darwin" ] || { echo "✗ Apple Music 推送只在 macOS 上可用(需要 osascript 读 Music.app)。"; exit 1; }
command -v osascript >/dev/null 2>&1 || { echo "✗ 未找到 osascript。"; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "✗ 未找到 curl。"; exit 1; }

echo "==> 安装 Apple Music 推送 → $URL (每 ${INTERVAL} 秒)..."
mkdir -p "$DIR/logs"

curl -fsSL "$URL/agent/read_music.js" -o "$DIR/read_music.js"

cat > "$DIR/sync_music.sh" <<'SYNC'
#!/bin/sh
JXA_FILE="$HOME/.kindle-dashboard/read_music.js"
ART_FILE="$HOME/.kindle-dashboard/music_artwork.jpg"
HASH_FILE="$HOME/.kindle-dashboard/music_artwork.sha256"
URL="${KINDLE_MUSIC_URL:-http://127.0.0.1:8585/api/music}"

rm -f "$ART_FILE"
KINDLE_MUSIC_ARTWORK_PATH="$ART_FILE" osascript >/dev/null 2>&1 <<'OSA' || true
set outPath to system attribute "KINDLE_MUSIC_ARTWORK_PATH"
try
  tell application "Music"
    if it is running and player state is not stopped then
      set t to current track
      if (count of artworks of t) > 0 then
        set artData to raw data of artwork 1 of t
        set f to open for access POSIX file outPath with write permission
        set eof f to 0
        write artData to f
        close access f
      end if
    end if
  end tell
on error
  try
    close access POSIX file outPath
  end try
end try
OSA

META=$(osascript -l JavaScript "$JXA_FILE" 2>/dev/null)
if [ $? -ne 0 ] || [ -z "$META" ]; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') 读取 Music.app 失败(可能未授予自动化权限)"
  exit 0
fi

BODY=$(printf '%s' "$META" | tr -d '\n' | sed 's/}$//')
ART_HASH=""
SEND_ART=0
if [ -s "$ART_FILE" ]; then
  if command -v shasum >/dev/null 2>&1; then
    ART_HASH=$(shasum -a 256 "$ART_FILE" | awk '{print $1}')
  elif command -v openssl >/dev/null 2>&1; then
    ART_HASH=$(openssl dgst -sha256 "$ART_FILE" | awk '{print $NF}')
  fi
  if [ -n "$ART_HASH" ]; then
    LAST_HASH=""
    [ -f "$HASH_FILE" ] && LAST_HASH=$(cat "$HASH_FILE" 2>/dev/null || true)
    BODY="$BODY,\"has_artwork\":true,\"artwork_hash\":\"sha256:$ART_HASH\""
    if [ "$ART_HASH" != "$LAST_HASH" ]; then
      SEND_ART=1
      printf '%s' "$ART_HASH" > "$HASH_FILE"
    fi
  else
    SEND_ART=1
    BODY="$BODY,\"has_artwork\":true"
  fi
  if [ "$SEND_ART" -eq 1 ]; then
    ART64=$(base64 < "$ART_FILE" | tr -d '\n')
    BODY="$BODY,\"artwork_mime\":\"image/jpeg\",\"artwork_data\":\"$ART64\""
  fi
else
  BODY="$BODY,\"has_artwork\":false"
  rm -f "$HASH_FILE"
fi
BODY="$BODY}"

RESP=$(curl -s -m 20 -X POST "$URL" -H "Content-Type: application/json" -d "$BODY" 2>&1)
if echo "$RESP" | grep -q '"status"'; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') 推送成功 -> $URL"
else
  echo "$(date '+%Y-%m-%d %H:%M:%S') 推送失败: $RESP"
fi
SYNC
chmod +x "$DIR/sync_music.sh"

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/sh</string><string>$DIR/sync_music.sh</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>KINDLE_MUSIC_URL</key><string>$URL/api/music</string>
    <key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
  </dict>
  <key>StartInterval</key><integer>$INTERVAL</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$DIR/logs/music.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/music.log</string>
</dict>
</plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load -w "$PLIST" 2>/dev/null && echo "✓ 已设 launchd 自启(每 ${INTERVAL} 秒推送)。" \
  || echo "⚠ launchd 加载失败。"

echo "==> 立即同步一次 —— macOS 可能会弹「允许控制 Music」,请点【允许】..."
KINDLE_MUSIC_URL="$URL/api/music" sh "$DIR/sync_music.sh"

echo
echo "✓ Apple Music 推送已安装。"
echo "  若没弹窗或误点了拒绝:系统设置 → 隐私与安全性 → 自动化,允许 终端/osascript 控制 Music。"
echo "  卸载: curl -fsSL $URL/agent/install_music.sh | sh -s -- uninstall"
