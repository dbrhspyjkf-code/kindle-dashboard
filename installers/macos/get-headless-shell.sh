#!/bin/bash
# 下载 chrome-headless-shell —— Chromium 的专用无头二进制,渲染看板时**不会在 macOS Dock 闪现图标**
# (完整 Chrome 的 --headless=new 是真浏览器、会建平台窗口 → Dock 抖动;这个壳不建窗口、不弹 Dock)。
# 落地到 ~/Library/Application Support/墨水桌面看板/chrome-headless-shell/,find_chrome 会自动优先用它。
# 用法:bash installers/macos/get-headless-shell.sh
# 国内下载慢可先:export https_proxy=http://代理地址(curl 会自动走它)。
set -e

DEST="$HOME/Library/Application Support/墨水桌面看板/chrome-headless-shell"
case "$(uname -m)" in
  arm64)  PLAT="mac-arm64" ;;
  x86_64) PLAT="mac-x64" ;;
  *) echo "✗ 不支持的架构:$(uname -m)"; exit 1 ;;
esac

echo "==> 查询 chrome-headless-shell($PLAT)最新稳定版下载地址…"
URL="$(curl -fsSL "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(next((x['url'] for x in d['channels']['Stable']['downloads']['chrome-headless-shell'] if x['platform']=='$PLAT'),''))" 2>/dev/null)"
[ -n "$URL" ] || { echo "✗ 拿不到下载地址(检查网络/代理)"; exit 1; }

echo "==> 下载(约 100MB):$URL"
TMP="$(mktemp -d)"
if ! curl -fSL "$URL" -o "$TMP/chs.zip"; then
  echo "✗ 下载失败。国内访问 Google 慢/不通时,先设代理再重试:export https_proxy=http://代理地址:端口"
  rm -rf "$TMP"; exit 1
fi

echo "==> 解压到 $DEST"
rm -rf "$DEST"; mkdir -p "$DEST"
unzip -oq "$TMP/chs.zip" -d "$DEST"
rm -rf "$TMP"

BIN="$(find "$DEST" -name chrome-headless-shell -type f | head -1)"
[ -n "$BIN" ] || { echo "✗ 解压后没找到 chrome-headless-shell 二进制"; exit 1; }
chmod +x "$BIN"
echo "✓ chrome-headless-shell 就绪:$BIN"
echo "  看板服务重启后渲染会自动改用它,Dock 不再抖动。"
