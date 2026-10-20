#!/usr/bin/env bash
# Forgeworks 冒烟测试
# 用真实浏览器（Chrome headless）跑一遍，不依赖任何 npm 包。
set -u

DIR="$(cd "$(dirname "$0")/.." && pwd)"
CHROME=""
for c in \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
  "$(command -v google-chrome 2>/dev/null)" \
  "$(command -v chromium 2>/dev/null)"; do
  [ -x "$c" ] && CHROME="$c" && break
done

if [ -z "$CHROME" ]; then
  echo "找不到 Chrome / Edge / Chromium，跳过冒烟测试" >&2
  exit 0
fi

OUT="$("$CHROME" --headless --disable-gpu --no-sandbox \
  --virtual-time-budget=8000 --dump-dom \
  "file://$DIR/tests/smoke.html" 2>/dev/null)"

# 只取第一段（页面脚本源码里也有同样的标记字符串，不能被误抓）
echo "$OUT" | awk '/SELFTEST_JSON_START/{f=1;next} /SELFTEST_JSON_END/{if(f){exit}} f'

if echo "$OUT" | grep -q '"fail": 0' && echo "$OUT" | grep -q '"runtimeErrors": 0'; then
  echo ""
  echo "✅ 冒烟测试通过"
  exit 0
else
  echo ""
  echo "❌ 冒烟测试失败"
  exit 1
fi
