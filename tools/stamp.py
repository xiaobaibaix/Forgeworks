#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Forgeworks 版本号打戳工具
=========================

解决的问题
-----------
浏览器（尤其内置预览面板）会缓存 .js/.css。改完代码刷新页面却还是旧行为，
是最难排查的一类 bug —— 代码是对的，只是浏览器没去拿。

对策是给每个资源引用加查询串 `src="js/main.js?v=20261021c"`。
但手工维护 37 处引用既烦又容易漏，所以有了这个脚本。

用法
----
    python3 tools/stamp.py            # 自动生成版本号（日期 + 当日序号）
    python3 tools/stamp.py 20261022a  # 指定版本号
    python3 tools/stamp.py --show     # 只看当前版本号，不改文件

版本号规则
----------
    YYYYMMDD + 当日字母序号（a, b, c, ...）
    同一天多次打戳自动递进，不用自己想名字。

它改哪些文件
------------
    index.html        所有 <script src> / <link href>
    tests/smoke.html  同上

它不改什么
----------
    main.js 里的版本戳是**运行时从自己的 script src 里读出来的**
    （`document.querySelector('script[src*="js/main.js"]')`），
    所以打完戳界面上显示的版本号会自动跟上，不需要同步改第二处。
"""

import re
import sys
import pathlib
import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGETS = ["index.html", "tests/smoke.html"]

# 匹配 src="...?v=xxx" 或 href="...?v=xxx"；也接受还没有 ?v= 的裸引用
ATTR_RE = re.compile(
    r'\b(src|href)="([^"]+?)(\?v=[^"]*)?"'
)


def current_stamp(text: str) -> str:
    m = re.search(r'\?v=([^"]+)', text)
    return m.group(1) if m else "(无)"


def next_stamp(old: str) -> str:
    """同一天递进字母序号：20261021c -> 20261021d；跨天则从 a 重新开始。"""
    today = datetime.date.today().strftime("%Y%m%d")
    m = re.match(r"^(\d{8})([a-z])$", old or "")
    if m and m.group(1) == today:
        nxt = chr(ord(m.group(2)) + 1)
        if nxt > "z":
            nxt = "z"
        return today + nxt
    return today + "a"


def restamp(text: str, stamp: str) -> str:
    def repl(m):
        attr, path, _old = m.group(1), m.group(2), m.group(3)
        # 外链（http/https/protocol-relative）不动
        if path.startswith(("http://", "https://", "//")):
            return m.group(0)
        return f'{attr}="{path}?v={stamp}"'
    return ATTR_RE.sub(repl, text)


def main():
    args = sys.argv[1:]
    if args and args[0] == "--show":
        for name in TARGETS:
            p = ROOT / name
            if p.exists():
                print(f"{name:20s} {current_stamp(p.read_text(encoding='utf-8'))}")
        return 0

    # 先看现有版本号，决定新版本号
    first = ROOT / TARGETS[0]
    old = current_stamp(first.read_text(encoding="utf-8"))
    stamp = args[0] if args else next_stamp(old)

    if not re.match(r"^[A-Za-z0-9._-]+$", stamp):
        print(f"版本号不合法（只允许字母数字 . _ -）：{stamp}", file=sys.stderr)
        return 1

    changed = 0
    for name in TARGETS:
        p = ROOT / name
        if not p.exists():
            print(f"跳过（不存在）：{name}")
            continue
        src = p.read_text(encoding="utf-8")
        out = restamp(src, stamp)
        if out != src:
            n = len(ATTR_RE.findall(src))
            p.write_text(out, encoding="utf-8")
            print(f"  {name:20s} 已打戳 {n} 处 -> ?v={stamp}")
            changed += 1

    if changed:
        print(f"\n完成。新版本号 {old} -> {stamp}")
        print("打开时请带上版本号，确保绕过缓存：")
        print(f"  http://127.0.0.1:8787/index.html?v={stamp}")
    else:
        print("没有文件需要改动。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
